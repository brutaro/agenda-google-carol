from __future__ import print_function
import datetime
import pickle
import os.path
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse  # Adicionar JSONResponse aqui
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from dateutil import parser
import re
from openai import OpenAI
from dotenv import load_dotenv
import os

# Carregar variáveis de ambiente e inicializar OpenAI no início
load_dotenv()
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

app = FastAPI()

# Configurar os templates e arquivos estáticos
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Atualizar a rota raiz para retornar HTMLResponse
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )

# Se modificar estes escopos, delete o arquivo token.pickle
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

def falar(texto):
    """Converte texto para fala"""
    tts = gTTS(text=texto, lang="pt-br")
    filename = "voice.mp3"
    tts.save(filename)
    playsound.playsound(filename)
    os.remove(filename)

def ouvir():
    """Captura áudio do microfone e converte para texto"""
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("Ouvindo...")
        audio = r.listen(source)
        texto = ""

        try:
            texto = r.recognize_google(audio, language='pt-BR')
            print(f"Você disse: {texto}")
        except Exception as e:
            print(f"Erro: {str(e)}")

    return texto.lower()

# Configuração do OAuth2
if os.getenv('GOOGLE_CLIENT_SECRET'):
    # Criar arquivo temporário com as credenciais
    import tempfile
    import json
    
    client_secrets_file = tempfile.NamedTemporaryFile(delete=False)
    client_secrets_file.write(os.getenv('GOOGLE_CLIENT_SECRET').encode())
    client_secrets_file.close()
    
    flow = Flow.from_client_secrets_file(
        client_secrets_file.name,
        scopes=SCOPES,
        redirect_uri='https://web-production-42764.up.railway.app/oauth2callback'  # URI fixa para produção
    )
    os.unlink(client_secrets_file.name)  # Remove o arquivo temporário após usar
else:
    # Fallback para desenvolvimento local
    flow = Flow.from_client_secrets_file(
        'client_secret_208149794146-eqenuk56dvgi0mnjegmgrj2qt5usfduu.apps.googleusercontent.com.json',
        scopes=SCOPES,
        redirect_uri='http://localhost:8000/oauth2callback'  # URI local para desenvolvimento
    )

@app.get("/login")
async def login():
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='select_account'
    )
    response = RedirectResponse(url=authorization_url)
    response.set_cookie("state", state)
    return response

@app.get("/oauth2callback")
async def oauth2callback(request: Request, code: str):
    flow.fetch_token(code=code)
    credentials = flow.credentials
    
    # Salvar as credenciais em uma sessão ou cookie seguro
    credentials_dict = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    
    response = RedirectResponse(url='/')
    response.set_cookie(
        "credentials",
        json.dumps(credentials_dict),
        httponly=True,
        secure=True
    )
    return response

# Modificar a função autenticar_google para usar as credenciais do cookie
def autenticar_google(request: Request):
    credentials_json = request.cookies.get("credentials")
    if not credentials_json:
        return RedirectResponse(url='/login')
    
    credentials_dict = json.loads(credentials_json)
    credentials = Credentials(
        **credentials_dict
    )
    
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            return RedirectResponse(url='/login')
    
    return build('calendar', 'v3', credentials=credentials)

# Primeiro, definir a função criar_evento fora do bloco try-except
def criar_evento(service, titulo, data_inicio, duracao=30, descricao=''):
    """Cria um evento no Google Calendar"""
    try:
        inicio = datetime.datetime.strptime(data_inicio, "%Y-%m-%d %H:%M")
        fim = inicio + datetime.timedelta(minutes=duracao)

        evento = {
            'summary': titulo,
            'description': descricao,
            'start': {
                'dateTime': inicio.isoformat(),
                'timeZone': 'America/Sao_Paulo',
            },
            'end': {
                'dateTime': fim.isoformat(),
                'timeZone': 'America/Sao_Paulo',
            },
        }

        print(f"Criando evento: {json.dumps(evento, indent=2)}")  # Log para debug
        evento_criado = service.events().insert(calendarId='primary', body=evento).execute()
        print(f"Evento criado com sucesso: {evento_criado['id']}")  # Log para confirmar criação
        return evento_criado
    except Exception as e:
        print(f"Erro ao criar evento: {str(e)}")  # Log de erro
        raise e

# Remover estas linhas:
# @app.get("/")
# def read_root():
#     headers = {"ngrok-skip-browser-warning": "true"}
#     return FileResponse("templates/index.html", headers=headers)
# 
# # Manter apenas esta versão

@app.get("/eventos")
async def listar_eventos_endpoint(request: Request):
    service = autenticar_google(request)
    if isinstance(service, RedirectResponse):
        return service
    
    try:
        eventos = listar_eventos(service)
        eventos_formatados = [{
            'summary': evento.get('summary', 'Sem título'),
            'start': {
                'dateTime': evento.get('start', {}).get('dateTime'),
                'date': evento.get('start', {}).get('date')
            },
            'end': {
                'dateTime': evento.get('end', {}).get('dateTime'),
                'date': evento.get('end', {}).get('date')
            }
        } for evento in eventos]
        
        response = {"eventos": eventos_formatados}
        headers = {"ngrok-skip-browser-warning": "true"}
        return JSONResponse(content=response, headers=headers)
    except Exception as e:
        return JSONResponse(
            content={"erro": f"Erro ao listar eventos: {str(e)}"},
            headers={"ngrok-skip-browser-warning": "true"}
        )

@app.post("/comando-voz")
async def processar_comando_voz(request: Request):
    headers = {"ngrok-skip-browser-warning": "true"}
    service = autenticar_google(request)
    if isinstance(service, RedirectResponse):
        return service
    
    try:
        data = await request.json()
        comando = data.get('texto', '')
        
        if not comando:
            return {"erro": "Nenhum texto fornecido"}
        
        if "agendar" in comando.lower() or "marcar" in comando.lower() or "reunião" in comando.lower():
            try:
                completion = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": f"""Extraia os detalhes do evento do texto em português.
                            Regras importantes:
                            1. Para reuniões, o título DEVE começar com 'Reunião com' seguido do nome EXATAMENTE como foi dito
                            2. Preserve títulos e tratamentos (Sr., Sra., Dr., etc.)
                            3. Mantenha nomes compostos e sobrenomes exatamente como mencionados
                            4. Se houver um assunto específico, inclua na descrição
                            5. Para datas:
                               - Se não especificado o ano, use SEMPRE o ano atual ({datetime.datetime.now().year})
                               - NUNCA use anos anteriores ao atual
                               - Se um ano for especificado e for anterior ao atual, use o ano atual
                            6. Para horários:
                               - Use EXATAMENTE o horário mencionado no comando
                               - Mantenha em formato 24h (14:00 em vez de 2:00 PM)
                               - Se for mencionado '5 da tarde' ou similar, converta para formato 24h (17:00)
                            7. Para duração:
                               - Extraia EXATAMENTE a duração mencionada no comando
                               - Converta expressões como 'uma hora' para 60 minutos
                               - Converta 'duas horas' para 120 minutos, etc.
                               - Se não especificado, use 30 minutos como padrão
                               - Suporte múltiplas horas (120, 180, 240 minutos, etc.)
                            8. Nunca modifique ou corrija a grafia dos nomes
                            9. NUNCA use 00:00 como horário padrão
                            
                            Retorne um JSON com os campos:
                            - titulo: string (ex: 'Reunião com Sr. Smith')
                            - descricao: string (assunto ou pauta da reunião)
                            - data: string (formato YYYY-MM-DD)
                            - hora: string (formato HH:MM)
                            - duracao: number (em minutos, respeitar a duração especificada)"""},
                        {"role": "user", "content": comando}
                    ]
                )
                
                detalhes = json.loads(completion.choices[0].message.content)
                data_hora = f"{detalhes['data']} {detalhes['hora']}"
                
                # Validar se a data está no formato correto
                try:
                    datetime.datetime.strptime(data_hora, "%Y-%m-%d %H:%M")
                except ValueError:
                    data_hora_convertida = processar_data_hora(f"{detalhes['data']} {detalhes['hora']}")
                    if not data_hora_convertida:
                        return {"erro": "Formato de data inválido"}
                    data_hora = data_hora_convertida
                
                evento = criar_evento(
                    service,
                    detalhes['titulo'],
                    data_hora,
                    detalhes.get('duracao', 30),
                    detalhes.get('descricao', '')
                )
                
                # Melhorar a mensagem de retorno
                inicio = evento['start']['dateTime']
                fim = evento['end']['dateTime']
                return {
                    "mensagem": f"Evento '{detalhes['titulo']}' agendado:\n" +
                              f"Início: {inicio}\n" +
                              f"Fim: {fim}\n" +
                              f"Duração: {detalhes.get('duracao', 30)} minutos"
                }
            except Exception as e:
                return {"erro": f"Erro ao processar o comando: {str(e)}"}
        
        elif "listar" in comando.lower() or "mostrar" in comando.lower():
            eventos = listar_eventos(service)
            resposta = "Aqui estão seus próximos eventos:\n"
            for evento in eventos:
                inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                resposta += f"- {evento['summary']} em {inicio}\n"
            return {"mensagem": resposta}
        
        return {"erro": "Comando não reconhecido"}
        
    except Exception as e:
        return {"erro": f"Erro ao processar requisição: {str(e)}"}

# Mover a função extrair_detalhes_evento para antes do if __name__ == '__main__'
def extrair_detalhes_evento(texto):
    """Extrai detalhes do evento usando GPT"""
    try:
        # Na rota /comando-voz, atualizar as instruções do sistema
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": """Extraia os detalhes do evento do texto em português.
                    Regras importantes:
                    1. Para reuniões, o título DEVE começar com 'Reunião com' seguido do nome completo da pessoa
                    2. Mantenha o nome exatamente como foi dito (ex: 'Sr. Smith' deve permanecer 'Sr. Smith')
                    3. Se houver um assunto específico, inclua na descrição
                    4. Para datas, priorize o ano atual se não especificado
                    5. Para horários, use formato 24h (14:00 em vez de 2:00 PM)
                    
                    Retorne um JSON com os campos:
                    - titulo: string (ex: 'Reunião com Sr. Smith')
                    - descricao: string (assunto ou pauta da reunião)
                    - data: string (formato YYYY-MM-DD)
                    - hora: string (formato HH:MM)
                    - duracao: number (em minutos, padrão 30)"""},
                {"role": "user", "content": comando}
            ]
        )
        
        # Converter a resposta para JSON
        import json
        detalhes = json.loads(completion.choices[0].message.content)
        
        # Formatar a data e hora
        data_hora = f"{detalhes['data']} {detalhes['hora']}"
        return {
            'titulo': detalhes['titulo'],
            'data_hora': data_hora,
            'duracao': detalhes.get('duracao', 30)
        }
    except Exception as e:
        print(f"Erro ao processar texto: {e}")
        return None

# Adicionar a função listar_eventos que estava faltando
def listar_eventos(service, max_results=10):
    """Lista os próximos eventos do calendário"""
    agora = datetime.datetime.utcnow().isoformat() + 'Z'
    eventos_result = service.events().list(
        calendarId='primary',
        timeMin=agora,
        maxResults=max_results,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    return eventos_result.get('items', [])

def processar_data_hora(data_hora_str):
    """Processa a data e hora do formato brasileiro para o formato ISO"""
    try:
        # Primeiro, tenta o formato completo YYYY-MM-DD HH:MM
        try:
            return datetime.datetime.strptime(data_hora_str, "%Y-%m-%d %H:%M").strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass

        # Tenta outros formatos comuns em português
        formatos = [
            "%d/%m/%Y %H:%M",
            "%d-%m-%Y %H:%M",
            "%d/%m/%y %H:%M",
            "%d-%m-%y %H:%M"
        ]

        for formato in formatos:
            try:
                data_hora = datetime.datetime.strptime(data_hora_str, formato)
                return data_hora.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue

        # Se não conseguiu converter com os formatos acima, tenta extrair a data e hora separadamente
        padrao_data = r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?'
        padrao_hora = r'(\d{1,2})(?::|h)(\d{2})'

        data_match = re.search(padrao_data, data_hora_str)
        hora_match = re.search(padrao_hora, data_hora_str)

        if data_match and hora_match:
            dia, mes, ano = data_match.groups()
            hora, minuto = hora_match.groups()

            # Se o ano não foi especificado, usa o ano atual
            if not ano:
                ano = datetime.datetime.now().year
            elif len(ano) == 2:
                ano = '20' + ano

            # Monta a data e hora no formato correto
            data_hora = datetime.datetime(int(ano), int(mes), int(dia), int(hora), int(minuto))
            return data_hora.strftime("%Y-%m-%d %H:%M")

        return None
    except Exception as e:
        print(f"Erro ao processar data e hora: {e}")
        return None

if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv('PORT', 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)