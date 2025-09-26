
import asyncio, io, uuid, re
from typing import Dict, List, Optional
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader
from docx import Document as DocxDocument
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from transformers import pipeline

app = FastAPI(title="Smart Doc Checker – Realtime")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS: Dict[str, Dict] = {}
WEBSOCKETS: Dict[str, WebSocket] = {}
_sent_splitter = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9(])')

def split_sentences(text: str) -> List[str]:
    text = text.replace("\r", " ").replace("\n", " ")
    parts = _sent_splitter.split(text.strip())
    return [p.strip() for p in parts if len(p.strip()) >= 4]

async def read_pdf(b: bytes) -> str:
    reader = PdfReader(io.BytesIO(b))
    return "\n".join([p.extract_text() or "" for p in reader.pages])

async def read_docx(b: bytes) -> str:
    doc = DocxDocument(io.BytesIO(b))
    return "\n".join([p.text for p in doc.paragraphs])

async def read_txt(b: bytes) -> str:
    try:
        return b.decode("utf-8", errors="ignore")
    except Exception:
        return ""

async def parse_file(name: str, data: bytes) -> str:
    n = name.lower()
    if n.endswith(".pdf"): return await read_pdf(data)
    if n.endswith(".docx"): return await read_docx(data)
    return await read_txt(data)

_nli_pipe = None
_nli_lock = asyncio.Lock()
async def get_nli():
    global _nli_pipe
    if _nli_pipe is None:
        async with _nli_lock:
            if _nli_pipe is None:
                _nli_pipe = pipeline("text-classification", model="roberta-large-mnli")
    return _nli_pipe

async def stream_contradictions(session_id: str):
    session = SESSIONS.get(session_id)
    if not session: return
    ws: Optional[WebSocket] = WEBSOCKETS.get(session_id)
    if ws is None: return

    docs = session["docs"]
    doc_sents = [{"name": d["name"], "sents": split_sentences(d["text"])} for d in docs]
    corpus, sent_idx = [], []
    for i, d in enumerate(doc_sents):
        for j, s in enumerate(d["sents"]):
            corpus.append(s); sent_idx.append((i,j))

    if len(corpus) < 2:
        await safe_send(ws, {"type":"done"})
        return

    vec = TfidfVectorizer(stop_words="english", max_df=0.9)
    X = vec.fit_transform(corpus)
    nli = await get_nli()

    top_k = 5
    min_cos = 0.15
    total = len(corpus)
    for idx, (di, si) in enumerate(sent_idx):
        sims = cosine_similarity(X[idx], X).ravel()
        cand_ids = sims.argsort()[::-1]
        checked = 0
        for cid in cand_ids:
            if cid == idx: continue
            score = float(sims[cid])
            dj, sj = sent_idx[cid]
            if dj == di: continue
            if score < min_cos: break
            checked += 1
            if checked > top_k: break
            s1, s2 = corpus[idx], corpus[cid]
            try:
                out1 = await asyncio.to_thread(nli, {"text": s1, "text_pair": s2})
                out2 = await asyncio.to_thread(nli, {"text": s2, "text_pair": s1})
                label1, score1 = out1[0]["label"].upper(), float(out1[0]["score"])
                label2, score2 = out2[0]["label"].upper(), float(out2[0]["score"])
                is_contra = ("CONTRADICTION" in label1) or ("CONTRADICTION" in label2)
                max_conf = max(score1, score2)
                if is_contra and max_conf >= 0.55:
                    sev = "High" if (score >= 0.45 and max_conf >= 0.90) else ("Medium" if max_conf >= 0.75 else "Low")
                    await safe_send(ws, {
                        "type":"contradiction",
                        "doc1": doc_sents[di]["name"],
                        "doc2": doc_sents[dj]["name"],
                        "sentence1": s1,
                        "sentence2": s2,
                        "severity": sev,
                        "confidence": round(max_conf*100,1),
                        "similarity": round(score,3),
                    })
            except Exception as e:
                await safe_send(ws, {"type":"error","message":f"NLI error: {e}"})
        if idx % 50 == 0:
            await safe_send(ws, {"type":"progress","processed":idx,"total":total})
    await safe_send(ws, {"type":"done"})

async def safe_send(ws: WebSocket, data: dict):
    try:
        await ws.send_json(data)
    except Exception:
        pass

@app.post("/upload")
async def upload(files: List[UploadFile] = File(...)):
    docs = []
    for f in files:
        content = await f.read()
        text = await parse_file(f.filename, content)
        docs.append({"name": f.filename, "text": text})
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {"docs": docs}
    return {"session_id": session_id, "count": len(docs)}

@app.websocket("/ws/contradictions")
async def ws_contradictions(ws: WebSocket, session_id: Optional[str] = None):
    await ws.accept()
    if not session_id or session_id not in SESSIONS:
        await ws.send_json({"type":"error","message":"Invalid or missing session_id"})
        await ws.close()
        return
    WEBSOCKETS[session_id] = ws
    try:
        await safe_send(ws, {"type":"info","message":"Starting analysis..."})
        await stream_contradictions(session_id)
    except WebSocketDisconnect:
        pass
    finally:
        if WEBSOCKETS.get(session_id) is ws:
            WEBSOCKETS.pop(session_id, None)

@app.get("/health")
def health():
    return {"status":"ok"}
