from fastapi import FastAPI, Request, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db import engine, SessionLocal
from models import Base, Scan
from worker import schedule_scan

Base.metadata.create_all(bind=engine)

app=FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates=Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, q: str = "", status: str = ""):
    session=SessionLocal()
    query=session.query(Scan)
    if q:
        query=query.filter(Scan.domain.contains(q))
    if status:
        query=query.filter(Scan.status == status)
    scans=query.order_by(Scan.created_at.desc()).all()
    session.close()
    return templates.TemplateResponse("dashboard.html",{
        "request":request,
        "scans":scans,
        "q":q,
        "status":status,
    })

@app.post("/scan")
async def start_scan(request: Request, domain: str = Form(""), file: UploadFile = None):
    domains=[]
    if domain.strip():
        domains.append(domain.strip())
    if file:
        content=(await file.read()).decode(errors="ignore")
        for line in content.splitlines():
            ln=line.strip()
            if ln and not ln.startswith("#"):
                domains.append(ln)
    seen=set()
    final=[]
    for d in domains:
        if d not in seen:
            seen.add(d)
            final.append(d)
    for d in final:
        schedule_scan(d)
    return RedirectResponse("/",303)

@app.get("/detail/{scan_id}", response_class=HTMLResponse)
def scan_detail(scan_id: int, request: Request):
    session=SessionLocal()
    scan=session.query(Scan).get(scan_id)
    session.close()
    if not scan:
        return HTMLResponse("Not found",404)
    return templates.TemplateResponse("detail.html",{"request":request,"scan":scan})
