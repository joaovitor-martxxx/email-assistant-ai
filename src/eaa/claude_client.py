import json
import logging
import re
from datetime import date, datetime

import anthropic
from .models import Email, Extraction
from .rate_limiter import RateLimiter
from .retry import retry_anthropic

log = logging.getLogger(__name__)

CATEGORIES = ("reuniao", "prazo_entrega", "acao_requerida",
              "informativo", "promocao", "irrelevante")
REQUIRED_KEYS = ("summary", "action_required", "deadline", "category", "keywords")
MAX_TOKENS = 500
MAX_FORMAT_ATTEMPTS = 2  # 1 chamada + 1 nova tentativa se o formato vier inválido
WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sábado", "domingo")


class InvalidClaudeResponse(ValueError):
    pass


def format_email(email: Email, today: date) -> str:
    return (f"Hoje: {today.isoformat()} ({WEEKDAYS[today.weekday()]})\n"
            f"De: {email.sender}\nAssunto: {email.subject}\n\n{email.body[:4000]}")


EXAMPLE_TODAY = date(2026, 10, 12)  # segunda-feira
# Todos os dados são fictícios (domínio example.test). Os prazos usam fuso -03:00.
EXAMPLES = [
    (Email("ex1", "Lia Exemplo <lia@example.test>", "Alinhamento do projeto Alfa",
           "Oi! Vamos alinhar o escopo na quarta-feira, às 15h, por videochamada. "
           "Confirma presença?", ""),
     {"summary": "Reunião de alinhamento do projeto Alfa na quarta às 15h; pede confirmação.",
      "action_required": True, "deadline": "2026-10-14T15:00:00-03:00",
      "category": "reuniao", "keywords": ["reunião", "projeto Alfa", "alinhamento"]}),
    (Email("ex2", "Beto Teste <beto@example.test>", "Relatório de vendas",
           "Preciso do relatório de vendas até sexta, dia 16, antes do fechamento do mês.", ""),
     {"summary": "Beto pede o relatório de vendas até sexta, dia 16.",
      "action_required": True, "deadline": "2026-10-16T23:59:00-03:00",
      "category": "prazo_entrega", "keywords": ["relatório", "vendas", "fechamento"]}),
    (Email("ex3", "Loja Modelo <ofertas@example.test>", "Só hoje: 40% de desconto",
           "Aproveite 40% de desconto em toda a loja. Cancelar inscrição: example.test/sair", ""),
     {"summary": "Promoção de 40% de desconto de uma loja.",
      "action_required": False, "deadline": None,
      "category": "promocao", "keywords": ["promoção", "desconto"]}),
    (Email("ex4", "Cris Amostra <cris@example.test>", "Proposta comercial",
           "Pode revisar a proposta em anexo quando puder? Preciso da sua opinião.", ""),
     {"summary": "Cris pede a revisão de uma proposta comercial, sem data definida.",
      "action_required": True, "deadline": None,
      "category": "acao_requerida", "keywords": ["proposta", "revisão"]}),
    (Email("ex5", "Boletim Exemplo <boletim@example.test>", "Resumo semanal de tecnologia",
           "Veja as principais notícias de tecnologia da semana.", ""),
     {"summary": "Boletim semanal com notícias de tecnologia.",
      "action_required": False, "deadline": None,
      "category": "informativo", "keywords": ["boletim", "tecnologia"]}),
    (Email("ex6", "Corrente Teste <corrente@example.test>", "Repasse para 10 amigos!!!",
           "Repasse esta mensagem para 10 amigos e tenha sorte.", ""),
     {"summary": "Mensagem em corrente sem relevância.",
      "action_required": False, "deadline": None,
      "category": "irrelevante", "keywords": ["corrente"]}),
]

INSTRUCTIONS = (
    "Você analisa e-mails e responde SOMENTE com um objeto JSON, sem texto fora dele "
    "e sem cercas de código.\n\n"
    "Chaves obrigatórias:\n"
    "- summary: resumo em uma frase, em português.\n"
    "- action_required: true se o destinatário precisa fazer algo; senão false.\n"
    "- deadline: data/hora ISO 8601 com fuso (ex.: 2026-10-14T15:00:00-03:00) do "
    "compromisso ou prazo; null se não houver. Se só houver a data, use 23:59. Resolva "
    "datas relativas (\"sexta\", \"amanhã\") a partir da linha \"Hoje\" da mensagem.\n"
    f"- category: exatamente uma de {', '.join(CATEGORIES)}.\n"
    "- keywords: lista de até 5 palavras-chave.\n"
)


def build_system() -> str:
    shots = "\n\n".join(
        f"Mensagem:\n{format_email(email, EXAMPLE_TODAY)}\n"
        f"Resposta:\n{json.dumps(result, ensure_ascii=False)}"
        for email, result in EXAMPLES)
    return f"{INSTRUCTIONS}\nExemplos:\n\n{shots}"


SYSTEM = build_system()


def parse_extraction(text: str) -> Extraction:
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidClaudeResponse(f"JSON inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidClaudeResponse("a resposta não é um objeto JSON")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise InvalidClaudeResponse(f"chaves ausentes: {', '.join(missing)}")
    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise InvalidClaudeResponse("summary deve ser texto não vazio")
    if not isinstance(data["action_required"], bool):
        raise InvalidClaudeResponse("action_required deve ser booleano")
    if data["category"] not in CATEGORIES:
        raise InvalidClaudeResponse(f"categoria fora da lista: {data['category']!r}")
    keywords = data["keywords"]
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        raise InvalidClaudeResponse("keywords deve ser lista de textos")
    deadline = data["deadline"]
    if deadline is not None:
        try:
            parsed = datetime.fromisoformat(deadline)
        except (TypeError, ValueError) as exc:
            raise InvalidClaudeResponse(f"deadline inválido: {deadline!r}") from exc
        if parsed.tzinfo is None:
            raise InvalidClaudeResponse(f"deadline sem fuso: {deadline!r}")
    return Extraction(summary=data["summary"], action_required=data["action_required"],
                      deadline=deadline, category=data["category"], keywords=keywords)


class ClaudeClient:
    def __init__(self, api_key: str, model: str, limiter: RateLimiter | None = None):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.limiter = limiter

    @retry_anthropic
    def analyze(self, email: Email, today: date | None = None) -> Extraction:
        content = format_email(email, today or date.today())
        for attempt in range(1, MAX_FORMAT_ATTEMPTS + 1):
            if self.limiter:
                self.limiter.acquire()
            msg = self.client.messages.create(
                model=self.model, max_tokens=MAX_TOKENS,
                system=SYSTEM, messages=[{"role": "user", "content": content}])
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            try:
                return parse_extraction(text)
            except InvalidClaudeResponse as exc:
                log.warning("resposta da Claude em formato inválido (tentativa %d/%d): %s",
                            attempt, MAX_FORMAT_ATTEMPTS, exc)
                if attempt == MAX_FORMAT_ATTEMPTS:
                    raise
