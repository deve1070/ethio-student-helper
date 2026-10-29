import sys, os, types, io, contextlib, logging, uuid, tempfile, json
sys.path.insert(0,".")
def stub(name, **a):
    m=types.ModuleType(name); m.__dict__.update(a); sys.modules[name]=m; return m
class _X:
    def __init__(s,*a,**k): pass
for n in ["docling","docling.backend","docling.backend.pypdfium2_backend","docling.datamodel","docling.datamodel.base_models","docling.datamodel.pipeline_options","docling.document_converter","docling_core","docling_core.transforms","docling_core.transforms.chunker","langchain_community","langchain_community.vectorstores","config","config.constants","config.settings","db.session","retriever","retriever.builder","utils.logging"]:
    stub(n)
sys.modules["docling.backend.pypdfium2_backend"].PyPdfiumDocumentBackend=_X
sys.modules["docling.datamodel.base_models"].InputFormat=types.SimpleNamespace(PDF=1)
sys.modules["docling.datamodel.pipeline_options"].PdfPipelineOptions=_X
sys.modules["docling.document_converter"].DocumentConverter=_X; sys.modules["docling.document_converter"].PdfFormatOption=_X
sys.modules["docling_core.transforms.chunker"].HierarchicalChunker=_X
sys.modules["langchain_community.vectorstores"].Chroma=_X
consts=types.SimpleNamespace(SUPPORTED_GRADES=[9,10,11,12],TEXTBOOK_CONTENT_ROOT="x",TEXTBOOK_COLLECTION_NAME="t")
sys.modules["config"].constants=consts; sys.modules["config.constants"]=consts
sys.modules["config.settings"].settings=types.SimpleNamespace(CHROMA_DB_PATH="x")
sys.modules["retriever.builder"].RetrieverBuilder=_X
sys.modules["utils.logging"].logger=logging.getLogger("t")
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import db.models as M
engine=create_engine("sqlite://",poolclass=StaticPool,connect_args={"check_same_thread":False})
M.Textbook.__table__.create(engine); M.Chunk.__table__.create(engine)
Session=sessionmaker(bind=engine); sys.modules["db.session"].SessionLocal=Session
import ingestion.textbook_ingest as T
from pathlib import Path
from reportlab.pdfgen import canvas

root=tempfile.mkdtemp()
def make_pdf(path, title):
    os.makedirs(os.path.dirname(path),exist_ok=True); c=canvas.Canvas(path)
    for i in range(4): c.drawString(60,800,f"Front matter {i} of {title}"); c.showPage()
    for printed in range(1,41):
        c.drawString(60,810,f"Unit {1+(printed-1)//10}: Topic {1+(printed-1)//10}"); c.drawString(60,780,str(printed))
        for k in range(20): c.drawString(60,740-k*25,f"{title} lesson text line {k} about forces and energy and cells")
        c.drawString(300,30,str(printed)); c.showPage()
    c.save()
layout={9:["biology","chemistry","citizenship_education","economics","geography","information_technology","physics"],10:["biology","physics","information technology"],11:["physics","Citizenship-Education"],12:["chemistry","physics"]}
for g,subs in layout.items():
    for s in subs: make_pdf(f"{root}/grade_{g}/{s}/{s.title()} Grade {g}.pdf", f"{s} {g}")

def dry(**kw):
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf): T.ingest_all(root,dry_run=True,**kw)
    return buf.getvalue()
ing=lambda out: [l for l in out.splitlines() if l.strip().startswith("ingest")]
skp=lambda out: [l for l in out.splitlines() if l.strip().startswith("skip")]
G=lambda l:int(l.split("grade ")[1].split(",")[0])

# 1) lowest grade first (a text sort would have put grade 9 LAST)
grades=[G(l) for l in ing(dry())]; assert grades==[9]*7+[10]*3+[11]*2+[12]*2, grades
# 2) --grade filter; several subjects at once, any spacing/case
assert {G(l) for l in ing(dry(grades=[10]))}=={10} and len(ing(dry(grades=[10])))==3
sub=ing(dry(only_subject="Physics, economics")); assert len(sub)==5 and sum("physics" in l for l in sub)==4 and sum("economics" in l for l in sub)==1
assert len(ing(dry(only_subject="physics",grades=[9])))==1
# folder names with spaces / capitals / hyphens land under ONE subject name in every grade
it=ing(dry(only_subject="Information Technology")); assert len(it)==2 and all("information_technology" in l for l in it) and {G(l) for l in it}=={9,10}, it
cz=ing(dry(only_subject="citizenship education")); assert len(cz)==2 and all("citizenship_education" in l for l in cz) and {G(l) for l in cz}=={9,11}, cz
assert T.normalize_subject(" Information-Technology ")=="information_technology" and T._subject_set("ICT x, Physics")=={"ict_x","physics"}
# 3) offsets/units found automatically for every synthetic book (4 front-matter pages)
allp=ing(dry()); print("sample plan line:", allp[0].strip()); assert all("offset 4 [auto" in l and "units: built from numbered headers (4 units)" in l for l in allp)

# ---- database with the accident: grade-9 economics/physics/IT/citizenship ingested, plus things that must NOT be touched
class Store:
    def __init__(s): s.deleted=[]; s.n=0
    def delete(s,ids): s.deleted+=list(ids)
    @property
    def _collection(s): return types.SimpleNamespace(count=lambda: s.n)
db=Session(); store=Store(); vids={}
def add_book(grade, subject, n=3):
    path=str(Path(root)/f"grade_{grade}"/subject/f"{subject.title()} Grade {grade}.pdf")
    tb=M.Textbook(id=uuid.uuid4(),grade=grade,subject=subject,title=f"{subject.title()} Grade {grade}",source_file_path=path); db.add(tb); db.flush()
    vids[(grade,subject)]=[]
    for i in range(n):
        v=f"{subject}{grade}-{i}"; db.add(M.Chunk(id=uuid.uuid4(),textbook_id=tb.id,vector_id=v,unit_or_chapter="U",page_start=1,page_end=1,text_excerpt="x")); vids[(grade,subject)].append(v)
    db.commit(); return tb
for s in ["economics","physics","information_technology","citizenship_education","geography","chemistry"]: add_book(9,s)
add_book(10,"physics"); store.n=7*3   # 7 books x 3 chunks in the database, Chroma agrees

# 4) --status: lists ingested + waiting, and compares Chroma with the database
buf=io.StringIO()
with contextlib.redirect_stdout(buf): T.list_status(db,store,Path(root))
out=buf.getvalue(); assert "INGESTED (7 books)" in out and "WAITING ON DISK" in out and "-> OK" in out
assert "grade  9  biology" in out.split("WAITING")[1] and "grade 12  physics" in out.split("WAITING")[1] and "grade  9  economics" not in out.split("WAITING")[1]
store.n=25
buf=io.StringIO()
with contextlib.redirect_stdout(buf): T.list_status(db,store,Path(root))
assert "MISMATCH: 4 vectors with no database row" in buf.getvalue()
store.n=21

# 5) --remove: refuses without YES, then deletes ONLY the four requested grade-9 books
four={"economics","physics","information_technology","citizenship_education"}
with contextlib.redirect_stdout(io.StringIO()) as _: n=T.remove_books(db,store,four,[9],ask=lambda p:"no")
assert n==0 and store.deleted==[] and db.query(M.Textbook).count()==7
buf=io.StringIO()
with contextlib.redirect_stdout(buf): n=T.remove_books(db,store,four,[9],ask=lambda p:"YES")
assert n==4 and "(3 chunks)" in buf.getvalue()
left={(t.grade,t.subject) for t in db.query(M.Textbook)}; assert left=={(9,"geography"),(9,"chemistry"),(10,"physics")}, left
want=[v for k in [(9,"economics"),(9,"physics"),(9,"information_technology"),(9,"citizenship_education")] for v in vids[k]]
assert sorted(store.deleted)==sorted(want) and db.query(M.Chunk).count()==9                     # grade-10 physics, geography, chemistry untouched
with contextlib.redirect_stdout(io.StringIO()) as _: assert T.remove_books(db,store,{"astronomy"},[9],assume_yes=True)==0
with contextlib.redirect_stdout(io.StringIO()) as _: assert T.remove_books(db,store,{"physics"},[11],assume_yes=True)==0   # right subject, wrong grade
assert db.query(M.Textbook).count()==3

# 6) the removed books are waiting again and come FIRST in grade 9; the others are skipped as already ingested
out=dry(grades=[9])
assert len(skp(out))==2 and all(("Geography" in l or "Chemistry" in l) for l in skp(out))
assert {l.split("]")[0] and l.split(":")[0].split()[1] for l in ing(out)}  # ingest lines exist
assert len(ing(out))==5 and not any("replaces" in l for l in ing(out))
print("INGESTION OPERATIONS VERIFIED: numeric grade order, --grade, comma subjects, auto offsets, --status (incl. mismatch), --remove (confirm/cancel/wrong grade/unknown), re-ingest plan")
