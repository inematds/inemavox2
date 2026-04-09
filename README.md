# inemaVOX 2

Suite de IA para videos: dublagem automatica, transcricao, corte de clips e download.

Funciona **sem GPU** — tudo via API cloud (Groq, OpenAI) ou processamento local em CPU.

---

## O que voce precisa antes de comecar

### 1. Instalar dependencias do sistema

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg python3 python3-pip git
```

**Mac (com Homebrew):**
```bash
brew install ffmpeg python git
```

---

### 2. Clonar o projeto

```bash
git clone https://github.com/inematds/inemavox2.git
cd inemavox2
```

---

### 3. Instalar dependencias Python

```bash
pip install -r requirements.txt
pip install -r api/requirements.txt
```

---

### 4. Configurar API Keys (importante!)

Copie o arquivo de exemplo e edite:

```bash
cp .env.example .env
```

Abra o arquivo `.env` em qualquer editor de texto e preencha:

```
GROQ_API_KEY=gsk_SuaChaveAqui
```

**Como obter a chave Groq (gratis):**
1. Acesse [console.groq.com](https://console.groq.com)
2. Crie uma conta gratuita
3. Va em "API Keys" e crie uma nova chave
4. Copie a chave e cole no `.env`

> A chave Groq e **gratis** e serve tanto para transcricao (Whisper) quanto para analise de clipes virais.

---

### 5. Iniciar o servidor

```bash
python -m uvicorn api.server:app --host 0.0.0.0 --port 8010 --reload
```

Abra no navegador: **http://localhost:8010**

---

## Como usar

### Dublar um video

1. Va em **Dublar** no menu
2. Cole a URL do YouTube (ou suba um arquivo local)
3. Selecione o idioma de destino (ex: Portugues)
4. Escolha a voz (Edge TTS tem varias vozes naturais)
5. Clique em **Iniciar** e aguarde

O video dublado sera gerado automaticamente.

---

### Transcrever um video

1. Va em **Transcrever**
2. Cole a URL ou suba o arquivo
3. Escolha o engine:
   - **Groq** (recomendado): rapido, precisa de internet
   - **Whisper CPU**: lento, funciona offline
4. Baixe o resultado em SRT, TXT ou JSON

---

### Cortar clips virais

1. Va em **Cortar**
2. Cole a URL do video
3. Escolha o modo:
   - **Manual**: voce define os timestamps (ex: `00:30-02:15, 05:00-07:30`)
   - **Viral**: IA identifica os melhores momentos automaticamente
   - **Por assunto**: IA divide o video por topicos
4. Baixe os clips em ZIP

---

### Baixar videos

1. Va em **Baixar**
2. Cole a URL (YouTube, TikTok, Instagram, Facebook, etc.)
3. Escolha a qualidade
4. Baixe o arquivo

---

## Configuracoes avancadas

### Trocar o engine de transcricao

No arquivo `.env`:

```bash
# Opcoes: groq | whisper-cpu | openai
STT_ENGINE=groq
```

| Engine | Velocidade | Requer internet | Custo |
|--------|-----------|-----------------|-------|
| `groq` | Muito rapido | Sim | Gratis |
| `whisper-cpu` | Lento | Nao | Gratis |
| `openai` | Rapido | Sim | Pago ($0.006/min) |

---

### Trocar o provider de LLM (analise de clipes)

```bash
# Groq e o padrao (gratis e rapido)
LLM_PROVIDER=groq

# Outras opcoes
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

---

### Traducao offline (sem internet)

Por padrao o projeto usa **M2M100** (modelo da Meta) para traducao — funciona **100% offline** sem precisar de API key.

Se quiser melhor qualidade contextual, configure um LLM cloud:

```bash
TRANSLATION_ENGINE=llm-cloud
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
```

---

## Solucao de problemas

### "GROQ_API_KEY nao configurada"
Voce nao criou o arquivo `.env` ou nao preencheu a chave. Siga o passo 4 acima.

### Transcricao muito lenta
Voce esta usando o engine `whisper-cpu`. Troque para `groq` no `.env`.

### Erro no download do video
Atualize o yt-dlp:
```bash
pip install -U yt-dlp
```

### O servidor nao inicia
Verifique se instalou todos os requisitos:
```bash
pip install -r requirements.txt
pip install -r api/requirements.txt
```

Verifique se o ffmpeg esta instalado:
```bash
ffmpeg -version
```

---

## Requisitos minimos

| Componente | Minimo |
|-----------|--------|
| Python | 3.10+ |
| RAM | 4 GB |
| Disco | 5 GB livres |
| Internet | Para Groq / Edge TTS / downloads |
| GPU | **Nao necessario** |

---

## Tecnologias

- **Transcricao**: Groq Whisper API ou Faster-Whisper (CPU)
- **Traducao**: M2M100 (Meta, offline) ou LLM cloud (Groq, OpenAI, Claude)
- **TTS**: Edge TTS (Microsoft, gratis) ou Piper (offline)
- **Video**: ffmpeg, yt-dlp
- **Backend**: FastAPI + WebSocket (Python)
