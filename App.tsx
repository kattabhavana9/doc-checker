
import React, { useRef, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL
const WS_URL = import.meta.env.VITE_WS_URL

type Row = {
  doc1: string; doc2: string; sentence1: string; sentence2: string;
  severity: 'High'|'Medium'|'Low'; confidence: number; similarity: number
}

export default function App(){
  const [files, setFiles] = useState<File[]>([])
  const [status, setStatus] = useState('Idle')
  const [progress, setProgress] = useState<string | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  const handleUpload = async () => {
    if (!files.length) return
    setStatus('Uploading...'); setRows([]); setProgress(null)

    const form = new FormData()
    files.forEach(f=>form.append('files', f))
    const res = await fetch(`${API_URL}/upload`,{method:'POST',body:form})
    const data = await res.json()

    const ws = new WebSocket(`${WS_URL}/ws/contradictions?session_id=${data.session_id}`)
    wsRef.current = ws
    setStatus('Analyzing...')
    ws.onmessage = (ev)=>{
      try{
        const msg = JSON.parse(ev.data)
        if (msg.type==='contradiction'){
          setRows(prev=>[msg, ...prev])
        } else if (msg.type==='progress'){
          setProgress(`${msg.processed}/${msg.total}`)
        } else if (msg.type==='info'){
          setStatus(msg.message)
        } else if (msg.type==='error'){
          setStatus(`Error: ${msg.message}`)
        } else if (msg.type==='done'){
          setStatus('Done')
          ws.close()
        }
      }catch{}
    }
    ws.onerror = ()=> setStatus('WebSocket error')
  }

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <header className="space-y-1">
        <h1 className="text-3xl font-bold">📑 Smart Doc Checker – AI-Powered Real-Time Contradictions</h1>
        <p className="text-gray-600">Upload multiple PDF/DOCX/TXT files. Contradictions stream live.</p>
      </header>

      <section className="p-4 bg-white rounded-xl border shadow-sm space-y-3">
        <input type="file" multiple accept=".pdf,.docx,.txt"
          onChange={e=>setFiles(Array.from(e.target.files || []))}
          className="block w-full text-sm text-gray-700 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-gray-200 hover:file:bg-gray-300"
        />
        <div className="flex items-center gap-3">
          <button onClick={handleUpload} className="px-4 py-2 bg-black text-white rounded-lg hover:opacity-90">
            Upload & Analyze
          </button>
          <span className="text-sm"><b>Status:</b> {status} {progress? `• Progress: ${progress}`:''}</span>
        </div>
        <div className="h-2 bg-gray-200 rounded overflow-hidden">
          <div className={`h-full ${status==='Analyzing...'?'animate-pulse':''} bg-gray-800`} style={{width: status==='Done'?'100%':'40%'}}/>
        </div>
      </section>

      <section className="p-4 bg-white rounded-xl border shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left bg-gray-100">
                <th className="p-2">Document 1</th>
                <th className="p-2">Document 2</th>
                <th className="p-2">Sentence 1</th>
                <th className="p-2">Sentence 2</th>
                <th className="p-2">Severity</th>
                <th className="p-2">Confidence</th>
                <th className="p-2">Similarity</th>
              </tr>
            </thead>
            <tbody>
              {rows.length===0 && <tr><td className="p-6 text-center text-gray-500" colSpan={7}>No contradictions yet. Upload to start.</td></tr>}
              {rows.map((r,i)=>(
                <tr key={i} className="border-b">
                  <td className="p-2">{r.doc1}</td>
                  <td className="p-2">{r.doc2}</td>
                  <td className="p-2">{r.sentence1}</td>
                  <td className="p-2">{r.sentence2}</td>
                  <td className="p-2">
                    <span className={r.severity==='High'?'text-red-600 font-semibold':r.severity==='Medium'?'text-orange-600 font-semibold':'text-green-600 font-semibold'}>{r.severity}</span>
                  </td>
                  <td className="p-2">{r.confidence}%</td>
                  <td className="p-2">{r.similarity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
