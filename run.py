"""Lancador de desenvolvimento. Uso: python run.py"""
import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print("Assistente Virtual Aguas Brasil")
    print("Abra no navegador:  http://localhost:8000/")
    print("=" * 60)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
