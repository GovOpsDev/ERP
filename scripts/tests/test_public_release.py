import importlib.util,json,subprocess,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('audit',Path(__file__).resolve().parents[1]/'check-public-release.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
class PublicSafety(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);subprocess.run(['git','init','-q',str(self.root)],check=True)
    def put(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    def rules(self):return {x['rule'] for x in audit.audit(self.root)['findings']}
    def test_untracked_secret_is_not_hidden_by_gitignore(self):
        self.put('.gitignore','.env\n');self.put('.env',('DATABASE_'+'PASSWORD')+chr(61)+repr('test'+'secret'))
        self.assertIn('private-file-type',self.rules());self.assertIn('literal-credential',self.rules())
    def test_token_and_key(self):
        self.put('bad.txt','ghp_'+'a'*30+'\n-----BEGIN '+'OPENSSH PRIVATE KEY-----');self.assertEqual(self.rules(),{'service-token','private-key'})
    def test_storage_state(self):
        self.put('session.json',json.dumps({'cookies':[],'origins':[]}));self.assertIn('browser-storage-state',self.rules())
    def test_public_readme_local_path(self):
        self.put('README.md','http://'+'localhost:8080 /home/'+'example/private/');self.assertEqual(self.rules(),{'public-readme-localhost','home-path'})
    def test_ignored_video_must_not_be_tracked(self):
        self.put('video/output/demo.mp4','synthetic');self.assertEqual(self.rules(),set());subprocess.run(['git','add','video/output/demo.mp4'],cwd=self.root,check=True);self.assertIn('tracked-private-output',self.rules())
    def test_changed_visual_evidence(self):
        self.put('demo.png','changed image bytes')
        self.put('docs/public-visual-review.json',json.dumps({'files':[{'file':'demo.png','sha256':'0'*64}]}))
        self.assertIn('visual-review-hash-changed',self.rules())
    def test_safe_source(self):
        self.put('demo.py','password = os.environ["DEMO_PASSWORD"]');self.put('.env.example','ODOO_DEMO_PASSWORD=<inject-from-secret-manager>');self.assertEqual(audit.audit(self.root)['status'],'PASS')
if __name__=='__main__':unittest.main()
