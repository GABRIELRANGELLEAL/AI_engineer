import requests
import json

BASE_URL = "http://localhost:8000"

class BackendTester:
    def __init__(self):
        self.session_id = None
        self.stream_response = None
    
    def upload_csv(self, filepath):
        """Upload de arquivo CSV"""
        with open(filepath, 'rb') as f:
            resp = requests.post(
                f"{BASE_URL}/upload-csv",
                files={"file": (filepath.split('/')[-1], f, "text/csv")}
            )
        print(f"Upload: {resp.json()}")
        return resp.json()
    
    def create_session(self, csv_name):
        """Criar sessão"""
        resp = requests.post(
            f"{BASE_URL}/session",
            json={"csv_name": csv_name}
        )
        data = resp.json()
        self.session_id = data['session_id']
        print(f"Session criada: {self.session_id}")
        print(f"Skills: {data['skills']}")
        return data
    
    def start_stream(self, message):
        """Iniciar stream SSE (não-bloqueante)"""
        self.stream_response = requests.get(
            f"{BASE_URL}/session/{self.session_id}/stream",
            params={"message": message},
            stream=True,
            timeout=120
        )
        print(f"\n📡 Stream iniciado! Aguardando eventos...\n")
        return self.stream_response
    
    def read_events(self, max_events=None):
        """Ler eventos do stream"""
        if not self.stream_response:
            print("❌ Stream não iniciado!")
            return
        
        count = 0
        for line in self.stream_response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    event = json.loads(line[6:])
                    self._print_event(event)
                    
                    if event['type'] == 'tool_call':
                        print("\n⏸️  AGUARDANDO AUTORIZAÇÃO!")
                        print(f"   Use: tester.approve_tool()  ou  tester.deny_tool()")
                        return event  # Pausa aqui
                    
                    if event['type'] == 'done':
                        print("\n✅ Stream finalizado!")
                        return None
                    
                    count += 1
                    if max_events and count >= max_events:
                        return
    
    def approve_tool(self):
        """Aprovar tool pendente"""
        resp = requests.post(
            f"{BASE_URL}/session/{self.session_id}/authorize",
            json={"approved": True}
        )
        print(f"✅ Tool aprovada! Continuando stream...\n")
        # Continua lendo eventos
        return self.read_events()
    
    def deny_tool(self):
        """Negar tool pendente"""
        resp = requests.post(
            f"{BASE_URL}/session/{self.session_id}/authorize",
            json={"approved": False}
        )
        print(f"❌ Tool negada! Continuando stream...\n")
        return self.read_events()
    
    def _print_event(self, event):
        """Formata e imprime evento"""
        etype = event['type']
        
        if etype == 'text':
            print(f"💬 {event['content']}")
        
        elif etype == 'tool_call':
            print(f"\n🔧 TOOL CALL: {event['name']}")
            print(f"   Input: {json.dumps(event['input'], indent=6)}")
        
        elif etype == 'tool_result':
            result = event['content']
            if len(result) > 200:
                result = result[:200] + "..."
            print(f"✅ Resultado: {result}")
        
        elif etype == 'skills_selected':
            print(f"🎯 Skills selecionadas")
        
        elif etype == 'error':
            print(f"❌ Erro: {event['message']}")
    
    def list_outputs(self):
        """Listar arquivos gerados"""
        resp = requests.get(f"{BASE_URL}/outputs")
        files = resp.json()['files']
        print(f"\n📂 Arquivos gerados ({len(files)}):")
        for f in files:
            print(f"   - {f['filename']}")
        return files

# ═══════════════════════════════════════════════════════════
# Uso interativo:
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    tester = BackendTester()
    
    # 1. Upload
    tester.upload_csv("workspace/teste.csv")
    
    # 2. Criar sessão
    tester.create_session("teste.csv")
    
    # 3. Stream com interação manual
    tester.start_stream("Analise o arquivo e mostre as primeiras 5 linhas")
    tester.read_events()  # Lê até encontrar tool_call
    
    # Agora você decide: aprovar ou negar
    # tester.approve_tool()  # ou tester.deny_tool()