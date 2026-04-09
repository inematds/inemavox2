"""Gerenciador de modelos - TTS voices, Whisper models, opcoes de configuracao."""

import os

# Vozes Edge TTS organizadas por codigo de idioma curto (pt, en, es, ...)
EDGE_VOICES = {
    "pt": [
        {"id": "pt-BR-AntonioNeural",   "name": "Antonio BR (Masculino)",  "gender": "male"},
        {"id": "pt-BR-FranciscaNeural", "name": "Francisca BR (Feminino)", "gender": "female"},
        {"id": "pt-BR-ThalitaNeural",   "name": "Thalita BR (Feminino)",   "gender": "female"},
        {"id": "pt-PT-DuarteNeural",    "name": "Duarte PT (Masculino)",   "gender": "male"},
        {"id": "pt-PT-RaquelNeural",    "name": "Raquel PT (Feminino)",    "gender": "female"},
    ],
    "en": [
        {"id": "en-US-GuyNeural",     "name": "Guy US (Male)",     "gender": "male"},
        {"id": "en-US-JennyNeural",   "name": "Jenny US (Female)", "gender": "female"},
        {"id": "en-US-AriaNeural",    "name": "Aria US (Female)",  "gender": "female"},
        {"id": "en-US-DavisNeural",   "name": "Davis US (Male)",   "gender": "male"},
        {"id": "en-GB-RyanNeural",    "name": "Ryan GB (Male)",    "gender": "male"},
        {"id": "en-GB-SoniaNeural",   "name": "Sonia GB (Female)", "gender": "female"},
    ],
    "es": [
        {"id": "es-ES-AlvaroNeural",  "name": "Alvaro ES (Masculino)", "gender": "male"},
        {"id": "es-ES-ElviraNeural",  "name": "Elvira ES (Femenino)",  "gender": "female"},
        {"id": "es-MX-JorgeNeural",   "name": "Jorge MX (Masculino)",  "gender": "male"},
        {"id": "es-MX-DaliaNeural",   "name": "Dalia MX (Femenino)",   "gender": "female"},
    ],
    "fr": [
        {"id": "fr-FR-HenriNeural",   "name": "Henri (Masculin)",  "gender": "male"},
        {"id": "fr-FR-DeniseNeural",  "name": "Denise (Feminin)",  "gender": "female"},
        {"id": "fr-FR-VivienneNeural","name": "Vivienne (Feminin)","gender": "female"},
    ],
    "de": [
        {"id": "de-DE-ConradNeural",  "name": "Conrad (Mannlich)", "gender": "male"},
        {"id": "de-DE-KatjaNeural",   "name": "Katja (Weiblich)",  "gender": "female"},
        {"id": "de-DE-AmalaNeural",   "name": "Amala (Weiblich)",  "gender": "female"},
    ],
    "it": [
        {"id": "it-IT-DiegoNeural",   "name": "Diego (Maschile)",  "gender": "male"},
        {"id": "it-IT-ElsaNeural",    "name": "Elsa (Femminile)",  "gender": "female"},
        {"id": "it-IT-IsabellaNeural","name": "Isabella (Femm.)",  "gender": "female"},
    ],
    "ja": [
        {"id": "ja-JP-KeitaNeural",   "name": "Keita (男性)",   "gender": "male"},
        {"id": "ja-JP-NanamiNeural",  "name": "Nanami (女性)",  "gender": "female"},
        {"id": "ja-JP-AoiNeural",     "name": "Aoi (女性)",     "gender": "female"},
    ],
    "zh": [
        {"id": "zh-CN-YunyangNeural", "name": "Yunyang (男)",  "gender": "male"},
        {"id": "zh-CN-XiaoxiaoNeural","name": "Xiaoxiao (女)", "gender": "female"},
        {"id": "zh-CN-YunxiNeural",   "name": "Yunxi (男)",    "gender": "male"},
    ],
    "ko": [
        {"id": "ko-KR-InJoonNeural",  "name": "InJoon (남성)", "gender": "male"},
        {"id": "ko-KR-SunHiNeural",   "name": "SunHi (여성)",  "gender": "female"},
    ],
    "ru": [
        {"id": "ru-RU-DmitryNeural",  "name": "Dmitry (Муж.)", "gender": "male"},
        {"id": "ru-RU-SvetlanaNeural","name": "Svetlana (Жен.)","gender": "female"},
    ],
}

WHISPER_MODELS = [
    {"id": "tiny", "name": "Tiny (39M)", "size_mb": 75, "quality": "baixa"},
    {"id": "small", "name": "Small (244M)", "size_mb": 460, "quality": "media"},
    {"id": "medium", "name": "Medium (769M)", "size_mb": 1500, "quality": "boa"},
]

ASR_ENGINES = [
    {
        "id": "groq",
        "name": "Groq Whisper API",
        "description": "Whisper large-v3 via API Groq. Muito rapido, barato, requer internet.",
        "detail": "Usa a API Groq para transcricao com Whisper large-v3-turbo. Qualidade excelente, velocidade muito superior ao local. Requer GROQ_API_KEY.",
        "needs_gpu": False,
        "needs_internet": True,
        "supports_languages": "all",
    },
    {
        "id": "whisper-cpu",
        "name": "Whisper CPU (Faster-Whisper)",
        "description": "Multi-idioma. Roda localmente em CPU, sem internet. Modelos tiny/small/medium.",
        "detail": "Usa Faster-Whisper (CTranslate2) em CPU. Modelos de 39M a 769M parametros. Mais lento que API mas funciona offline.",
        "needs_gpu": False,
        "needs_internet": False,
        "supports_languages": "all",
    },
    {
        "id": "openai",
        "name": "OpenAI Whisper API",
        "description": "Whisper via API OpenAI. Confiavel, $0.006/min.",
        "detail": "Usa a API oficial OpenAI para transcricao com Whisper. Requer OPENAI_API_KEY.",
        "needs_gpu": False,
        "needs_internet": True,
        "supports_languages": "all",
    },
]

TTS_ENGINES = [
    {
        "id": "edge",
        "name": "Edge TTS (Microsoft)",
        "needs_gpu": False,
        "needs_internet": True,
        "quality": "excelente",
        "description": "Vozes naturais de alta qualidade. Rapido e gratis, requer internet.",
        "detail": "Usa a API gratuita da Microsoft (mesmas vozes do Windows e Edge). Suporta dezenas de idiomas com multiplas vozes por idioma. Qualidade excelente, velocidade rapida, sem custo de GPU. Unica desvantagem: precisa de conexao com internet.",
    },
    {
        "id": "piper",
        "name": "Piper (Leve)",
        "needs_gpu": False,
        "needs_internet": False,
        "quality": "razoavel",
        "description": "Ultra-leve e offline. Roda em qualquer hardware sem internet.",
        "detail": "Motor TTS minimalista que roda em CPU sem internet. Muito rapido e leve, ideal para ambientes sem rede ou com hardware limitado. Qualidade inferior aos outros motores - voz soa mais robotica. Use quando offline total for requisito.",
    },
]

TRANSLATION_ENGINES = [
    {
        "id": "m2m100",
        "name": "M2M100 (Facebook)",
        "needs_gpu": False,
        "models": ["418M", "1.2B"],
        "description": "Traducao offline multi-idioma. Funciona sem internet e sem GPU.",
        "detail": "Modelo multilingual da Meta. Suporta 100 idiomas em qualquer direcao sem passar pelo ingles. Modelo 418M rapido e leve, 1.2B melhor qualidade. Roda em CPU. Bom para frases curtas, pode perder contexto em frases longas.",
    },
    {
        "id": "llm-cloud",
        "name": "LLM Cloud (Groq/OpenAI/Claude)",
        "needs_gpu": False,
        "models": "dynamic",
        "description": "Traducao via LLM na nuvem. Melhor qualidade contextual, requer API key.",
        "detail": "Usa LLM via API cloud (Groq, OpenAI, Anthropic, etc). Qualidade superior ao M2M100 pois entende contexto, expressoes idiomaticas e tom. Requer API key configurada.",
    },
]

CONTENT_TYPES = [
    {
        "id": "tutorial",
        "name": "Tutorial / Apresentacao",
        "description": "Screencast, tutorial, demo, social media. Fala natural, sem cortes.",
        "detail": "Fala 20% mais rapida para compensar que o portugues e mais longo que o ingles. Se ainda sobrar audio, o video congela o frame ate a fala terminar — sem cortar nenhuma palavra. A melhor opcao para tutoriais curtos onde o conteudo completo e mais importante que o timing exato.",
        "presets": {"sync": "extend", "maxstretch": 1.5, "no_truncate": True, "tts_rate": "+20%"},
    },
    {
        "id": "palestra",
        "name": "Palestra / Talking Head",
        "description": "Vlog, entrevista, podcast com video. Equilibra timing e conteudo.",
        "detail": "Comprime a fala ate 30% para caber no tempo original. Se a frase traduzida for muito longa, corta palavras do final para manter sincronia com o video. Bom para quando o apresentador aparece na tela e o timing labial importa moderadamente.",
        "presets": {"sync": "smart", "maxstretch": 1.3, "tolerance": 0.1},
    },
    {
        "id": "curso",
        "name": "Curso / Aula",
        "description": "Conteudo educacional. Nunca corta frases, comprime bastante se preciso.",
        "detail": "Mantem todas as frases completas sem cortar nenhuma palavra. Se a traducao ficar mais longa que o original, comprime a velocidade da fala em ate 2x. Ideal para cursos e aulas onde perder conteudo e inaceitavel, mesmo que a fala fique um pouco mais rapida.",
        "presets": {"sync": "fit", "maxstretch": 1.4, "no_truncate": True},
    },
    {
        "id": "podcast",
        "name": "Podcast / Entrevista",
        "description": "Conversa longa. Frases completas, velocidade moderada.",
        "detail": "Mantem frases completas e comprime ate 50% se necessario. Bom equilibrio entre preservar o conteudo e nao distorcer demais a voz. Para podcasts e entrevistas longas onde o ouvinte precisa de todo o contexto.",
        "presets": {"sync": "fit", "maxstretch": 1.5, "no_truncate": True},
    },
    {
        "id": "apresentacao",
        "name": "Apresentacao / Demo",
        "description": "Tutorial, screencast, demo de software. Timing preciso com a tela.",
        "detail": "Prioriza sincronizacao com o que acontece na tela. Comprime ate 15% e corta texto se necessario para que a fala acompanhe as acoes no video. Essencial para demos onde o narrador diz 'clique aqui' e o cursor se move.",
        "presets": {"sync": "smart", "maxstretch": 1.15, "tolerance": 0.05},
    },
    {
        "id": "narracao",
        "name": "Narracao / Documentario",
        "description": "Sem apresentador. Voz natural, video congela se preciso.",
        "detail": "Fala 100% natural sem nenhuma compressao ou corte. Se a traducao for mais longa que o original, o video congela no ultimo frame ate a fala terminar. O video final pode ficar mais longo que o original. Perfeito para documentarios e narracoes onde a qualidade da voz e prioridade maxima.",
        "presets": {"sync": "extend", "maxstretch": 2.0, "no_truncate": True},
    },
    {
        "id": "shorts",
        "name": "Shorts / Reels",
        "description": "Video curto. Timing exato, cada frame importa.",
        "detail": "Timing ultra-preciso para videos curtos onde cada segundo conta. Comprime no maximo 10% e corta texto agressivamente se necessario. A duracao do video e identica ao original. Para TikTok, Reels, Shorts onde a sincronia visual e critica.",
        "presets": {"sync": "smart", "maxstretch": 1.1, "tolerance": 0.03},
    },
    {
        "id": "filme",
        "name": "Filme / Serie",
        "description": "Lip-sync importa. Prefere cortar a desincronizar.",
        "detail": "Otimizado para cenas com atores falando. Comprime ate 20% e corta texto para manter sincronia labial. Usa diarizacao para detectar diferentes personagens. Timing preciso para que a voz combine com os movimentos da boca.",
        "presets": {"sync": "smart", "maxstretch": 1.2, "tolerance": 0.05, "diarize": True},
    },
]

SUPPORTED_LANGUAGES = [
    {"code": "pt", "name": "Portugues"},
    {"code": "en", "name": "Ingles"},
    {"code": "es", "name": "Espanhol"},
    {"code": "fr", "name": "Frances"},
    {"code": "de", "name": "Alemao"},
    {"code": "it", "name": "Italiano"},
    {"code": "ja", "name": "Japones"},
    {"code": "zh", "name": "Chines"},
    {"code": "ko", "name": "Coreano"},
    {"code": "ru", "name": "Russo"},
    {"code": "ar", "name": "Arabe"},
    {"code": "hi", "name": "Hindi"},
]


def get_all_options() -> dict:
    """Retorna todas as opcoes disponiveis para a interface."""
    return {
        "tts_engines": TTS_ENGINES,
        "translation_engines": TRANSLATION_ENGINES,
        "whisper_models": WHISPER_MODELS,
        "asr_engines": ASR_ENGINES,
        "edge_voices": EDGE_VOICES,
        "content_types": CONTENT_TYPES,
        "languages": SUPPORTED_LANGUAGES,
    }
