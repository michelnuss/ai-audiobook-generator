# Audiolivro

Um aplicativo para ouvir o livro sendo lido em voz alta, direto no celular.

## Como instalar

### 1. Instalar o Python

Se o computador ainda não tem Python instalado:

- **Windows**: Acesse [python.org/downloads](https://www.python.org/downloads/) e baixe o instalador. Durante a instalação, marque a opção **"Add Python to PATH"**.
- **Mac**: Abra o Terminal e digite `python3 --version`. Se não estiver instalado, o Mac vai oferecer para instalar automaticamente.

### 2. Instalar as dependências

Abra o Terminal (Mac) ou o Prompt de Comando (Windows) e navegue até a pasta do aplicativo:

```
cd caminho/para/a/pasta/app
```

Depois, instale as dependências:

```
pip install -r requirements.txt
```

### 3. Configurar o arquivo .env

Na pasta `app`, crie um arquivo chamado `.env` (o nome do arquivo é literalmente `.env`). Copie o conteúdo do arquivo `.env.example` e preencha com as suas informações:

```
TTS_PROVIDER=azure
TTS_FALLBACK_TO_AZURE=true

AZURE_SPEECH_KEY=sua_chave_azure_aqui
AZURE_SPEECH_REGION=eastus

ELEVENLABS_API_KEY=sua_chave_elevenlabs_aqui
ELEVENLABS_VOICE_ID=GIuLCSVfgJaUuh7hYOY8

DOCX_PATH=caminho/para/o/livro.docx
```

- **TTS_PROVIDER**: Qual motor de voz o aplicativo usa. Valores possíveis: `azure` ou `elevenlabs`. Veja a seção **Como mudar o provedor de voz** abaixo.
- **TTS_FALLBACK_TO_AZURE**: Quando `true` e `TTS_PROVIDER=elevenlabs`, o app **usa ElevenLabs até acabar a cota ou dar erro de quota**; em seguida **passa a usar Azure automaticamente** (é preciso ter credenciais Azure no `.env`). Assim você aproveita os créditos do ElevenLabs primeiro e continua ouvindo com Azure sem mudar o `.env` à mão. O fallback **só** é ativado quando a API do ElevenLabs indica **quota/créditos** (não confunde com chave inválida). Ao **reiniciar o servidor**, o app tenta ElevenLabs de novo do zero.
- **AZURE_SPEECH_KEY** e **AZURE_SPEECH_REGION**: Necessários quando `TTS_PROVIDER=azure`. A chave e a região do Azure Speech (exemplo de região: `eastus`, `brazilsouth`).
- **ELEVENLABS_API_KEY** e **ELEVENLABS_VOICE_ID**: Necessários quando `TTS_PROVIDER=elevenlabs`. A chave da API e o ID da voz no [ElevenLabs](https://elevenlabs.io/).
- **DOCX_PATH**: O caminho completo para o arquivo .docx do livro. Exemplo no Windows: `C:\Users\MeuNome\Documents\livro.docx`. Exemplo no Mac: `/Users/MeuNome/Documents/livro.docx`.

### Como mudar o provedor de voz

O aplicativo pode usar **Azure Speech** (voz neural em português) ou **ElevenLabs** (outra voz, conforme o ID que você configurar).

1. Abra o arquivo `.env` na pasta `app`.
2. Altere a linha `TTS_PROVIDER`:
   - `TTS_PROVIDER=azure` — usa Azure Speech. É preciso ter `AZURE_SPEECH_KEY` e `AZURE_SPEECH_REGION` preenchidos corretamente.
   - `TTS_PROVIDER=elevenlabs` — usa ElevenLabs. É preciso ter `ELEVENLABS_API_KEY` e `ELEVENLABS_VOICE_ID` preenchidos. Com `TTS_FALLBACK_TO_AZURE=true` e credenciais Azure preenchidas, após esgotar a cota do ElevenLabs o app **continua com Azure**.
3. Salve o arquivo e **reinicie o servidor** (pare com `Ctrl+C` e suba de novo com `uvicorn`).

Você pode deixar as duas credenciais no `.env` e só trocar `TTS_PROVIDER` quando quiser testar um ou outro. O áudio gerado fica em cache na pasta `audio_cache` (cada provedor tem entradas separadas no cache).

### 4. Iniciar o aplicativo

No Terminal ou Prompt de Comando, dentro da pasta `app`, digite:

```
uvicorn main:app --host 0.0.0.0 --port 8000
```

Se estiver usando este projeto nesta pasta no Mac, você pode copiar e colar este comando completo no Terminal:

```
cd "/Users/michelnussbacher/Desktop/livro/app" && python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Você verá uma mensagem dizendo que o servidor está rodando. **Não feche essa janela** enquanto estiver usando o aplicativo.

## Como abrir no navegador do computador

Com o servidor rodando no mesmo computador, abra o navegador e digite:

```
http://localhost:8000
```

Você também pode usar:

```
http://127.0.0.1:8000
```

## Como abrir no iPhone na mesma rede Wi-Fi

### Descobrir o endereço IP do computador

O iPhone precisa saber o endereço do computador na rede Wi-Fi:

- **Windows**: Abra o Prompt de Comando e digite `ipconfig`. Procure por **"Endereço IPv4"** (geralmente começa com `192.168...`).
- **Mac**: Vá em Preferências do Sistema > Rede. O endereço IP aparece na tela (geralmente começa com `192.168...`).

### Abrir no iPhone

1. Certifique-se de que o iPhone e o computador estão conectados **na mesma rede Wi-Fi**.
2. No Safari, Chrome ou outro navegador do iPhone, digite:

```
http://ENDEREÇO_IP:8000
```

Por exemplo, se o IP do computador for `192.168.1.50`, digite:

```
http://192.168.1.50:8000
```

3. O aplicativo vai abrir e você pode escolher um capítulo para ouvir.

## Observações importantes

- O **computador precisa estar ligado** e com o servidor rodando para o aplicativo funcionar no navegador do computador e no iPhone.
- O iPhone e o computador precisam estar **na mesma rede Wi-Fi**.
- Para parar o servidor, pressione `Ctrl+C` na janela do Terminal/Prompt de Comando.
- O aplicativo lembra onde você parou. Na próxima vez que abrir, ele oferece a opção de continuar de onde parou.
