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

class PaymentRequest(BaseModel):
    email: str
    amount: int  # Em centavos (exemplo: $5.00 → 500)

@app.post("/create-checkout-session/")
async def create_checkout_session(payment: PaymentRequest):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "brl",
                    "product_data": {"name": "Acesso ao Analisador de Vídeo"},
                    "unit_amount": payment.amount,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url="https://decentralizedtech.com.br/ia_futebol_sucesso.html",
            cancel_url="https://sisaut.vercel.app/ia_futebol_cancel.html",
            customer_email=payment.email
        )
        return {"checkout_url": session.url}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/webhook/")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session["customer_email"]
        payment_id = session["payment_intent"]

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
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
