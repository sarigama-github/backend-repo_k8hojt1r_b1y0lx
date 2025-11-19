import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime

from database import db, create_document, get_documents
from bson.objectid import ObjectId

from schemas import ChatRequest, ChatResponse, Conversation, Message

app = FastAPI(title="Panny Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConversationOut(BaseModel):
    id: str
    title: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: Optional[str] = None


# Utils

def to_str_id(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return value


def serialize_doc(doc: dict) -> dict:
    out = {**doc}
    if "_id" in out:
        out["id"] = to_str_id(out.pop("_id"))
    for k, v in list(out.items()):
        if isinstance(v, ObjectId):
            out[k] = str(v)
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


@app.get("/schema")
def get_schemas():
    return {
        "schemas": [
            {
                "name": "conversation",
                "fields": list(Conversation.model_fields.keys())
            },
            {
                "name": "message",
                "fields": list(Message.model_fields.keys())
            },
        ]
    }


# Conversations
@app.get("/api/conversations", response_model=List[ConversationOut])
def list_conversations(limit: int = 20):
    items = db["conversation"].find().sort("updated_at", -1).limit(limit) if db else []
    results = []
    for it in items:
        doc = serialize_doc(it)
        results.append(ConversationOut(
            id=doc.get("id"),
            title=doc.get("title"),
            user_id=doc.get("user_id"),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        ))
    return results


@app.get("/api/conversations/{conversation_id}/messages", response_model=List[MessageOut])
def list_messages(conversation_id: str, limit: int = 100):
    if db is None:
        raise HTTPException(500, detail="Database not available")
    items = db["message"].find({"conversation_id": conversation_id}).sort("created_at", 1).limit(limit)
    results = []
    for it in items:
        doc = serialize_doc(it)
        results.append(MessageOut(
            id=doc.get("id"),
            conversation_id=doc.get("conversation_id"),
            role=doc.get("role"),
            content=doc.get("content"),
            created_at=doc.get("created_at"),
        ))
    return results


# Simple empathetic responder
EMPATHY_SEED = [
    "I'm here with you.",
    "That sounds really tough, thank you for sharing it.",
    "It's okay to feel this way.",
    "Let's take it one small step at a time.",
]


def generate_reply(user_text: str) -> str:
    text = user_text.strip()
    if not text:
        return "I'm here whenever you're ready."
    lowered = text.lower()
    if any(word in lowered for word in ["anxious", "anxiety", "worried", "panic"]):
        return "I hear the anxiety showing up. Try a slow breath with me: in for 4, hold for 4, out for 6. What tends to help even a little when this feeling visits?"
    if any(word in lowered for word in ["sad", "down", "tired"]):
        return "Feeling low can be heavy. What would be the gentlest next right thing for you—water, a stretch, texting a friend?"
    if any(word in lowered for word in ["angry", "frustrated", "mad"]):
        return "Anger is a signal. Want to unpack what boundary or need might be underneath it?"
    if any(word in lowered for word in ["can't sleep", "insomnia", "sleep"]):
        return "Rest can be hard when the mind is busy. Would a quick grounding—naming 5 things you can see, 4 you can touch—be okay to try?"
    return f"{EMPATHY_SEED[0]} Tell me more about what's on your mind."


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if db is None:
        raise HTTPException(500, detail="Database not available")

    # Ensure conversation exists
    conversation_id = request.conversation_id
    now = datetime.utcnow()

    if not conversation_id:
        conv = Conversation(title=None, user_id=None)
        conversation_id = create_document("conversation", conv)
    else:
        # touch updated_at
        db["conversation"].update_one({"_id": ObjectId(conversation_id)}, {"$set": {"updated_at": now}})

    # Store user message
    user_msg = {
        "conversation_id": conversation_id,
        "role": "user",
        "content": request.message,
        "created_at": now,
        "updated_at": now,
    }
    db["message"].insert_one(user_msg)

    # Generate assistant reply
    reply_text = generate_reply(request.message)

    bot_msg = {
        "conversation_id": conversation_id,
        "role": "assistant",
        "content": reply_text,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    db["message"].insert_one(bot_msg)

    # Update conversation timestamp
    db["conversation"].update_one({"_id": ObjectId(conversation_id)}, {"$set": {"updated_at": datetime.utcnow()}})

    # Return response (with latest messages)
    msgs = db["message"].find({"conversation_id": conversation_id}).sort("created_at", 1).limit(50)
    messages_out = []
    for m in msgs:
        d = serialize_doc(m)
        messages_out.append(Message(**{
            "conversation_id": d.get("conversation_id"),
            "role": d.get("role"),
            "content": d.get("content"),
            "created_at": datetime.fromisoformat(d.get("created_at")) if isinstance(d.get("created_at"), str) else d.get("created_at"),
        }))

    return ChatResponse(conversation_id=conversation_id, reply=reply_text, messages=[Message(**{
        "conversation_id": m.conversation_id,
        "role": m.role,
        "content": m.content,
        "created_at": m.created_at,
    }) for m in messages_out])


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
