"""Recovery is a coherent authenticated group, never a directory copy."""
import json
from pathlib import Path
from contextlib import closing
import shutil
import sqlite3
import unittest
from unittest.mock import patch
import test_authenticated_workspace as helpers
from accounting_harness.workspace import Workspace


class RecoveryTests(unittest.TestCase):
    setUpClass = classmethod(helpers.ApplicationBoundaryTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.ApplicationBoundaryTests.tearDownClass.__func__)
    def setUp(self):
        helpers.ApplicationBoundaryTests.setUp(self)
        self.root = self.root.resolve()
    call = helpers.ApplicationBoundaryTests.call
    native_draft = helpers.ApplicationBoundaryTests.native_draft

    def api(self):
        import accounting_harness.recovery as recovery
        return recovery

    def test_verified_group_restores_both_entities_and_revokes_sessions(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.recovery'), 'Verified recovery must be implemented')
        r = self.api()
        self.call('reviewer', 'approve-post', self.native_draft())
        before = Workspace(self.root / 'alpha').state()
        shutil.copytree(self.root / 'alpha', self.root / 'copied')
        with self.assertRaisesRegex(ValueError, 'scope'):
            Workspace(self.root / 'copied')
        backup = self.root / 'backup'
        result = r.backup_group(self.access.path, backup)
        self.assertEqual(len(result['entities']), 2)
        restored = self.root / 'restored'
        r.restore_group(backup, restored, activate=True)
        from accounting_harness.access import AccessStore, AccessDenied
        from accounting_harness.authenticated import AuthenticatedWorkspace
        access = AccessStore(restored / 'access.sqlite3')
        with closing(sqlite3.connect(self.access.path)) as old, closing(sqlite3.connect(access.path)) as new:
            old_audit=old.execute('SELECT * FROM access_audit ORDER BY sequence').fetchall()
            new_audit=new.execute('SELECT * FROM access_audit ORDER BY sequence').fetchall()
            self.assertEqual(new_audit[:-1],old_audit)
            self.assertEqual(new_audit[-1][1],'recovery-activation')
            self.assertEqual(new.execute('SELECT count(*) FROM sessions WHERE revoked_at IS NULL').fetchone()[0],0)
        with self.assertRaises(AccessDenied): access.session(self.tokens['owner'])
        token = access.login('owner', 'Synthetic fixture passphrase owner')
        after = AuthenticatedWorkspace(access).call(token, 'alpha', 'state')
        for key in ('journals', 'trial_balance', 'sources', 'drafts', 'runs'):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(Workspace(restored / 'entities/0001').catalog.entity_id, 'beta')
        self.assertFalse(Workspace(restored / 'entities/0000', enable_providers=True).enable_providers)

    def test_shared_application_locks_refuse_maintenance(self):
        self.assertIsNotNone(__import__('importlib.util').util.find_spec('accounting_harness.maintenance'), 'Maintenance exclusion must be implemented')
        from accounting_harness.maintenance import maintenance_lock, workspace_lock, access_lock
        from accounting_harness.persistence import PersistenceBusy
        instance = Workspace(self.root / 'alpha')
        with maintenance_lock(workspace_lock(instance.root), exclusive=True):
            with self.assertRaises(PersistenceBusy): instance.state()
            with self.assertRaises(PersistenceBusy): Workspace(instance.root)
        with maintenance_lock(access_lock(self.access.path), exclusive=True):
            with self.assertRaises(PersistenceBusy): self.access.session(self.tokens['owner'])

    def test_repeat_relocation_preserves_first_origin_and_rejects_copy_or_forgery(self):
        r = self.api()
        first = self.root / 'first'; second = self.root / 'second'
        r.backup_group(self.access.path, self.root / 'b1')
        r.restore_group(self.root / 'b1', first, activate=True)
        r.backup_group(first / 'access.sqlite3', self.root / 'b2')
        r.restore_group(self.root / 'b2', second, activate=True)
        with Workspace(second / 'entities/0000').storage() as (_, _, _, _, engine):
            self.assertEqual(engine._path, str(self.root / 'alpha/runs.sqlite3'))
            self.assertEqual(engine._physical_path, str(second / 'entities/0000/runs.sqlite3'))
        shutil.copytree(second, self.root / 'copy2')
        with self.assertRaises(ValueError): Workspace(self.root / 'copy2/entities/0000')
        receipt = second / 'entities/0000/recovery-relocation.json'
        value = json.loads(receipt.read_text()); value['record']['logical_root'] = str(self.root / 'beta')
        receipt.write_text(json.dumps(value))
        with self.assertRaises(ValueError): Workspace(second / 'entities/0000')

    def test_manifest_payload_and_path_attacks_are_refused(self):
        r=self.api(); backup=self.root/'backup'; r.backup_group(self.access.path,backup)
        original=(backup/'manifest.json').read_bytes()
        manifest=json.loads(original)
        def reseal(value):
            value['backup_id']=r.sha(r.canonical({k:v for k,v in value.items() if k!='backup_id'}).encode())
            (backup/'manifest.json').write_text(json.dumps(value))
        for mutation in ('version','missing','extra','traversal','entity','context','duplicate-entity','optional','schema'):
            value=json.loads(original)
            if mutation=='version': value['version']=2
            elif mutation=='missing': value['files'].pop('entities/0001/runs.sqlite3')
            elif mutation=='extra': value['files']['surprise.sqlite3']=value['files']['access.sqlite3']
            elif mutation=='traversal': value['entities'][0]['directory']='../escape'
            elif mutation=='entity': value['entities'][0]['entity_id']='other'
            elif mutation=='context': value['entities'][0]['context_digest']='0'*64
            elif mutation=='duplicate-entity': value['entities'][1]['entity_id']='alpha'
            elif mutation=='optional': value['entities'][0]['presence']['qbo-outbox.sqlite3']=True
            else: value['files']['access.sqlite3']['tables']={}
            reseal(value)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): r.restore_group(backup,self.root/'rejected',activate=True)
            self.assertFalse((self.root/'rejected').exists())
        (backup/'manifest.json').write_bytes(original[:-1]+b',"version":1}')
        with self.assertRaises(ValueError): r.verify_backup(backup)
        (backup/'manifest.json').write_bytes(original)
        target=backup/'entities/0000/runs.sqlite3'; saved=target.read_bytes(); target.write_bytes(b'corrupt')
        with self.assertRaises(ValueError): r.verify_backup(backup)
        target.write_bytes(saved)
        target.unlink(); target.symlink_to(self.root/'alpha/runs.sqlite3')
        with self.assertRaises(ValueError): r.verify_backup(backup)
        target.unlink(); target.write_bytes(saved)
        import os
        target.unlink(); os.link(self.root/'alpha/runs.sqlite3',target)
        with self.assertRaises(ValueError): r.verify_backup(backup)
        target.unlink(); target.write_bytes(saved)
        (backup/'unknown.txt').write_text('not allowed')
        with self.assertRaises(ValueError): r.verify_backup(backup)
        (backup/'unknown.txt').unlink()
        for destination in (self.root/'alpha/nested', self.root/'alpha',backup/'inside'):
            with self.subTest(destination=destination),self.assertRaises(ValueError): r.restore_group(backup,destination,activate=True)
        with self.assertRaises(ValueError): r.restore_group(backup,self.root/'no-activation')

    def test_corrupt_schema_and_missing_ungranted_entity_abort_whole_group(self):
        r=self.api()
        optional=self.root/'beta/runs.sqlite3'
        original=optional.read_bytes(); optional.unlink()
        with self.assertRaises(ValueError): r.backup_group(self.access.path,self.root/'missing')
        optional.write_bytes(original)
        with closing(sqlite3.connect(optional)) as db: db.execute('PRAGMA user_version=999')
        with self.assertRaises(ValueError): r.backup_group(self.access.path,self.root/'wrong-schema')
        optional.write_bytes(original)
        (self.root/'beta/unknown.db').write_bytes(original)
        with self.assertRaises(ValueError): r.backup_group(self.access.path,self.root/'unknown-store')

    def test_every_fault_boundary_never_exposes_partial_destination(self):
        r=self.api(); events=[]
        before=r._inspect(self.root/'alpha/ledger.sqlite3','ledger.sqlite3','alpha')
        r.backup_group(self.access.path,self.root/'template',fault=events.append)
        for i,event in enumerate(events):
            output=self.root/f'b-fault-{i}'
            def fail(label):
                if label==event: raise RuntimeError('injected '+event)
            with self.subTest(stage=event),self.assertRaises(RuntimeError): r.backup_group(self.access.path,output,fault=fail)
            self.assertEqual(output.exists(),event=='after_publish')
            if output.exists(): r.verify_backup(output)
            self.assertFalse(list(self.root.glob('.'+output.name+'-staging-*')))
        events=[]
        r.restore_group(self.root/'template',self.root/'restore-template',activate=True,fault=events.append)
        for i,event in enumerate(events):
            output=self.root/f'r-fault-{i}'
            def fail(label):
                if label==event: raise RuntimeError('injected '+event)
            with self.subTest(stage=event),self.assertRaises(RuntimeError): r.restore_group(self.root/'template',output,activate=True,fault=fail)
            self.assertEqual(output.exists(),event=='after_publish')
            if output.exists(): Workspace(output/'entities/0000').state()
            self.assertFalse(list(self.root.glob('.'+output.name+'-staging-*')))

        self.assertEqual(r._inspect(self.root/'alpha/ledger.sqlite3','ledger.sqlite3','alpha'),before)

    def test_application_and_raw_sqlite_writers_cannot_cross_snapshot(self):
        from accounting_harness.persistence import PersistenceBusy
        r=self.api(); instance=Workspace(self.root/'alpha'); observed=[]
        def writer(label):
            if label=='before_snapshot:access.sqlite3':
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=2) as executor:
                    direct=executor.submit(instance.register_source,dict(document_id='blocked',document_date='2026-01-05',amount='1.00',counterparty='Synthetic',description='Blocked concurrent write'))
                    authenticated=executor.submit(self.facade.call,self.tokens['owner'],'alpha','state')
                    with self.assertRaises(PersistenceBusy): direct.result()
                    with self.assertRaises(PersistenceBusy): authenticated.result()
                for path in (self.access.path,self.root/'beta/ledger.sqlite3',self.root/'alpha/runs.sqlite3'):
                    with closing(sqlite3.connect(path,timeout=0)) as db:
                        with self.assertRaises(sqlite3.OperationalError): db.execute('BEGIN IMMEDIATE')
                observed.append(True)
        r.backup_group(self.access.path,self.root/'backup',fault=writer)
        self.assertEqual(observed,[True])
        with closing(sqlite3.connect(self.root/'alpha/ledger.sqlite3',timeout=0)) as db:
            db.execute('BEGIN IMMEDIATE')
            with self.assertRaises(PersistenceBusy): r.backup_group(self.access.path,self.root/'busy')
        self.assertFalse((self.root/'busy').exists())
        instance.state()  # Every acquired gate was released after the failed attempt.

    def test_both_effect_before_checkpoint_runs_resume_without_duplicate_draft(self):
        from accounting_harness.recovery_demo import interrupt_legacy, interrupt_operational
        from accounting_harness import operational_agent as agent
        from contextlib import closing
        r=self.api(); w=Workspace(self.root/'alpha',actor_id='synthetic-preparer')
        data=interrupt_legacy(w); interrupt_operational(w)
        before=w.state(); self.assertEqual(len(before['drafts']),2)
        checkpoints={}
        for name in ('runs.sqlite3','agent-runs.sqlite3'):
            with closing(sqlite3.connect(w.root/name)) as db:
                checkpoints[name]=db.execute('SELECT * FROM run_checkpoints ORDER BY run_id,sequence').fetchall()
        r.backup_group(self.access.path,self.root/'backup')
        r.restore_group(self.root/'backup',self.root/'restored',activate=True)
        restored=Workspace(self.root/'restored/entities/0000',actor_id='synthetic-preparer')
        for name,rows in checkpoints.items():
            with closing(sqlite3.connect(restored.root/name)) as db:
                self.assertEqual(db.execute('SELECT * FROM run_checkpoints ORDER BY run_id,sequence').fetchall(),rows)
        restored.action('run',data)
        self.assertEqual(agent.continue_run(restored,'recovery-operational',agent.OfflinePlayback())['reason'],'tool_result_recovered')
        self.assertEqual(restored.state()['drafts'],before['drafts'])
        self.assertEqual(restored.state()['journals'],[])
        # The relocated dispatch lock stays beside the physical DB, never at origin.
        self.assertTrue((restored.root/'runs.sqlite3.dispatch.lock').exists())

    def test_pending_evidence_preserved_and_recovered_transports_disabled(self):
        r=self.api(); w=Workspace(self.root/'alpha')
        with w.storage() as (registry,_,_,_,_):
            registry.register(dict(w.cases[0]['document'],document_id='pending'),actor_id='fixture')
        before=w.state()
        r.backup_group(self.access.path,self.root/'backup')
        r.restore_group(self.root/'backup',self.root/'restored',activate=True)
        restored=Workspace(self.root/'restored/entities/0000',enable_providers=True,ollama_model='test-model')
        self.assertEqual(restored.state()['sources'],before['sources'])
        self.assertEqual([p['available'] for p in restored.providers()],[True,False,False])
        for action,data in [('qbo-read',dict(batch_id='no')),('qbo-export-send',dict(export_id='no')),('qbo-export-check',dict(export_id='no'))]:
            with self.assertRaisesRegex(ValueError,'transports are disabled'): restored.action(action,data)
        self.assertFalse((restored.root/'qbo-staging.sqlite3').exists())

    def test_recovery_cli_drill_is_available(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-recovery'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('without duplicate drafts',result.stdout)

    def test_publish_kernel_no_replace_keeps_a_racing_destination(self):
        r=self.api()
        self.assertTrue(callable(getattr(r,'_rename_new',None)), 'Publication must use a kernel no-replace rename')
        source=self.root/'staged'; source.mkdir(); (source/'verified').write_text('verified')
        target=self.root/'racing'; target.mkdir()
        with self.assertRaises(FileExistsError): r._rename_new(source,target)
        self.assertTrue((source/'verified').exists()); self.assertEqual(list(target.iterdir()),[])
        target.rmdir(); r._rename_new(source,target)
        self.assertFalse(source.exists()); self.assertEqual((target/'verified').read_text(),'verified')

    def test_missing_subsidiary_table_is_not_accepted_as_current_schema(self):
        r=self.api()
        with closing(sqlite3.connect(self.root/'alpha/ledger.sqlite3')) as db:
            db.execute('DROP TABLE budget_versions'); db.commit()
        with self.assertRaisesRegex(ValueError,'schema|table'): r.backup_group(self.access.path,self.root/'bad-schema')

    def test_run_scope_mismatch_rejected_even_when_manifest_hash_is_recomputed(self):
        r=self.api(); backup=self.root/'backup'; r.backup_group(self.access.path,backup)
        value=json.loads((backup/'manifest.json').read_text())
        value['entities'][0]['logical_root']=str(self.root/'beta')
        value['backup_id']=r.sha(r.canonical({k:v for k,v in value.items() if k!='backup_id'}).encode())
        (backup/'manifest.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'scope'): r.verify_backup(backup)

    def test_optional_run_created_after_restore_uses_first_logical_origin(self):
        from accounting_harness.operational_agent import OperationalRunEngine
        r=self.api(); r.backup_group(self.access.path,self.root/'backup')
        r.restore_group(self.root/'backup',self.root/'restored',activate=True)
        restored=Workspace(self.root/'restored/entities/0000')
        with restored.storage() as (_,_,store,_,_):
            with OperationalRunEngine(restored,store) as engine:
                self.assertEqual(engine._path,str(self.root/'alpha/agent-runs.sqlite3'))
        r.backup_group(self.root/'restored/access.sqlite3',self.root/'second-backup')
        r.restore_group(self.root/'second-backup',self.root/'second-restored',activate=True)
        second=Workspace(self.root/'second-restored/entities/0000')
        with second.storage() as (_,_,store,_,_):
            with OperationalRunEngine(second,store) as engine:
                self.assertEqual(engine._path,str(self.root/'alpha/agent-runs.sqlite3'))

    def test_optional_dangling_symlink_and_unusual_database_name_are_refused(self):
        r=self.api(); optional=self.root/'alpha/agent-runs.sqlite3'
        optional.symlink_to(self.root/'missing-store')
        with self.assertRaisesRegex(ValueError,'symlink'): r.backup_group(self.access.path,self.root/'dangling')
        optional.unlink()
        shutil.copyfile(self.root/'alpha/runs.sqlite3',self.root/'alpha/hidden-history.data')
        with self.assertRaisesRegex(ValueError,'Unknown workspace database'): r.backup_group(self.access.path,self.root/'hidden')

    def test_same_version_column_and_protection_damage_are_rejected(self):
        r=self.api(); path=self.root/'alpha/ledger.sqlite3'; original=path.read_bytes()
        for statement in ('ALTER TABLE budget_versions RENAME COLUMN result_json TO unsupported_result_json',
                          'DROP TRIGGER budget_versions_no_update'):
            with closing(sqlite3.connect(path)) as db:
                db.execute(statement); db.commit()
            with self.subTest(statement=statement),self.assertRaisesRegex(ValueError,'schema'):
                r.backup_group(self.access.path,self.root/'unsupported')
            self.assertFalse((self.root/'unsupported').exists())
            path.write_bytes(original)

    def test_receipt_replacement_syncs_parent_after_the_rename(self):
        import os,stat
        r=self.api(); events=[]; original_sync=os.fsync; original_replace=os.replace
        def sync(descriptor):
            events.append('directory-sync' if stat.S_ISDIR(os.fstat(descriptor).st_mode) else 'file-sync')
            return original_sync(descriptor)
        def replace(source,target):
            events.append('replace'); return original_replace(source,target)
        with patch.object(r.os,'fsync',sync),patch.object(r.os,'replace',replace):
            r._replace_receipt(self.root/'receipt.json',{'verified':True})
        self.assertEqual(events,['file-sync','replace','directory-sync'])
        self.assertEqual(json.loads((self.root/'receipt.json').read_text()),{'verified':True})

    def test_supported_migrations_and_all_optional_service_schemas_recover(self):
        from accounting_harness.workspace import (PayablesService, ReceivablesService, AdvancesService,
            BankFeeService, PrepaidService, ReconciliationService)
        r=self.api(); w=Workspace(self.root/'alpha')
        # Initialize in a different order; the original schema was also migrated
        # through ledger 1..6. Explicitly exercise delivered review11->12 again.
        with w.storage() as (registry,ledger,_,_,_):
            for service in (PrepaidService, BankFeeService, AdvancesService, ReceivablesService, PayablesService):
                service(ledger,registry)
            ReconciliationService(ledger)
            db=ledger._connection
            seal=db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone()[0]
            db.execute('DROP TRIGGER review_schema_no_update'); db.execute('UPDATE review_schema SET version=11')
            db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
            db.execute('DROP TRIGGER intent_required_at_seal'); db.execute(seal.replace(",'nonoperating-cash-v1'",''))
        w=Workspace(w.root)  # Supported migrations finish before maintenance.
        r.backup_group(self.access.path,self.root/'migrated')
        r.restore_group(self.root/'migrated',self.root/'restored',activate=True)
        restored=Workspace(self.root/'restored/entities/0000')
        self.assertEqual(restored.budget_inputs('2026-01'),w.budget_inputs('2026-01'))
        self.assertEqual(restored.state()['journals'],[])

    def test_constraint_damage_and_resealed_protection_damage_are_refused(self):
        r=self.api(); backup=self.root/'backup'; r.backup_group(self.access.path,backup)
        # A same-version constraint alteration remains valid SQLite but unsupported
        # by the current auth contract. Read-only recovery must still reject it.
        with closing(sqlite3.connect(self.access.path)) as db:
            sql=db.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
            self.assertIn('disabled IN (0,1)',sql)
            db.execute('PRAGMA writable_schema=ON')
            db.execute("UPDATE sqlite_master SET sql=? WHERE name='users'",(sql.replace('disabled IN (0,1)','disabled IN (0,1,2)'),))
            version=db.execute('PRAGMA schema_version').fetchone()[0]
            db.execute(f'PRAGMA schema_version={version+1}'); db.commit()
        with self.assertRaisesRegex(ValueError,'schema'): r.backup_group(self.access.path,self.root/'constraint-damage')
        # Recompute ordinary damage hashes after dropping a snapshot protection:
        # supported structure, not a self-authored hash, must reject publication.
        relative='entities/0000/ledger.sqlite3'; path=backup/relative
        with closing(sqlite3.connect(path)) as db:
            db.execute('DROP TRIGGER budget_versions_no_update'); db.commit()
            schema_rows=db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        manifest=json.loads((backup/'manifest.json').read_text()); info=manifest['files'][relative]
        info.update(size=path.stat().st_size,sha256=r.sha(path.read_bytes()))
        info['tables']['_schema_identity']['digest']=r.sha(r.canonical(schema_rows).encode())
        manifest['backup_id']=r.sha(r.canonical({k:v for k,v in manifest.items() if k!='backup_id'}).encode())
        (backup/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'schema'): r.restore_group(backup,self.root/'rejected',activate=True)
        self.assertFalse((self.root/'rejected').exists())
