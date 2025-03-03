from fastapi import FastAPI, HTTPException, Request
import stripe
import sqlite3
from pydantic import BaseModel
import os
import uvicorn

# Configuração do Stripe
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
stripe.api_key = STRIPE_SECRET_KEY


app = FastAPI()

# Criar banco de dados
conn = sqlite3.connect("payments.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    email TEXT,
    status TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS accesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id TEXT UNIQUE,
    email TEXT,
    used INTEGER DEFAULT 0,
    FOREIGN KEY (payment_id) REFERENCES payments(id)
)
""")
conn.commit()
conn.close()

# Modelo de requisição de pagamento
class PaymentRequest(BaseModel):
    email: str
    amount: int  # Em centavos (exemplo: $5.00 → 500)

@app.post("/create-payment-intent/")
async def create_payment_intent(payment: PaymentRequest):
    """Cria um PaymentIntent no Stripe"""
    try:
        intent = stripe.PaymentIntent.create(
            amount=payment.amount,
            currency="usd",
            receipt_email=payment.email
        )
        return {"client_secret": intent.client_secret}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/webhook/")
async def stripe_webhook(request: Request):
    """Webhook para capturar pagamentos confirmados"""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]
        email = payment_intent["receipt_email"]
        payment_id = payment_intent["id"]

        # Registrar pagamento e conceder um acesso único
        conn = sqlite3.connect("payments.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO payments (id, email, status) VALUES (?, ?, ?)",
                       (payment_id, email, "paid"))
        cursor.execute("INSERT INTO accesses (payment_id, email, used) VALUES (?, ?, 0)",
                       (payment_id, email))
        conn.commit()
        conn.close()

        print(f"Pagamento confirmado: {email} pode acessar o analisador de vídeo")

    return {"status": "success"}

@app.post("/use-access/{email}")
async def use_access(email: str):
    """Verifica se o usuário tem um acesso válido e consome-o"""
    conn = sqlite3.connect("payments.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM accesses WHERE email = ? AND used = 0 LIMIT 1", (email,))
    access = cursor.fetchone()

    if access:
        cursor.execute("UPDATE accesses SET used = 1 WHERE id = ?", (access[0],))
        conn.commit()
        conn.close()
        return {"access": True, "message": "Acesso concedido"}
    
    conn.close()
    return {"access": False, "message": "Nenhum acesso disponível"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))  # Usa a porta do Render ou 8000 como padrão
    uvicorn.run(app, host="0.0.0.0", port=port)