
from fastapi import FastAPI, Request, Form, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from .database import Base, engine, SessionLocal
from .models import Scan
from .worker import pipeline_for_domain
import threading

Base.metadata.create_all(engine)

app=FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates=Jinja2Templates(directory="templates")

@app.get("/")
def home(request:Request):
    db=SessionLocal()
    scans=db.query(Scan).order_by(Scan.id.desc()).all()
    db.close()
    return templates.TemplateResponse("dashboard.html",{"request":request,"scans":scans})

@app.post("/scan")
async def scan(domain:str=Form(""), file:UploadFile|None=None):
    domains=[]
    if domain.strip(): domains.append(domain.strip())
    if file:
        for l in (await file.read()).decode().splitlines():
            l=l.strip()
            if l: domains.append(l)
    db=SessionLocal()
    for d in domains:
        s=Scan(domain=d,status="pending"); db.add(s); db.commit()
        threading.Thread(target=pipeline_for_domain,args=(d,s.id)).start()
    db.close()
    return RedirectResponse("/",303)

@app.get("/detail/{id}")
def detail(id:int, request:Request):
    db=SessionLocal()
    s=db.query(Scan).get(id)
    db.close()
    return templates.TemplateResponse("detail.html",{"request":request,"scan":s})
