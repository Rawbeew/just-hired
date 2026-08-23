import re, subprocess, tempfile, os, zipfile, xml.etree.ElementTree as ET
os.chdir(r"C:/Users/alaga/AppData/Local/hermes/ghwork/just-hired")
src = open('index.html', encoding='utf-8').read()
s = re.search(r'<script>(.*)</script>', src, re.S).group(1)
stub = """const __noop=()=>{};
const document={getElementById:()=>({innerHTML:'',style:{},classList:{add:__noop,remove:__noop,toggle:__noop},addEventListener:__noop,value:'',textContent:''}),querySelectorAll:()=>[],querySelector:()=>null,createElement:()=>({style:{},setAttribute:__noop,appendChild:__noop}),addEventListener:__noop,body:{appendChild:__noop}};
const window={addEventListener:__noop,location:{href:'',search:''}};const localStorage={getItem:()=>null,setItem:__noop};
"""
js = stub + s + """
const fs=require('fs');
const bytes=zipStore(textToDocx("A & B <tag> \\u0022q\\u0022"));
fs.writeFileSync(process.env.OUT, Buffer.from(bytes));
console.log('ok');
"""
out = os.path.join(tempfile.gettempdir(), 't.docx')
p = os.path.join(tempfile.gettempdir(), 't.js')
open(p, 'w', encoding='utf-8').write(js)
r = subprocess.run(['node', p], capture_output=True, text=True,
                   env=dict(os.environ, OUT=out))
print("rc:", r.returncode); print(r.stdout); print(r.stderr[:600])
if r.returncode == 0:
    with zipfile.ZipFile(out) as z:
        print("bad:", z.testzip())
        doc = z.read('word/document.xml').decode()
    ET.fromstring(doc); print("xml ok; has amp:", "&amp;" in doc)
os.remove(p)
