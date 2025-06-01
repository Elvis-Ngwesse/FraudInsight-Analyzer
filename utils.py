import random
from faker import Faker
import logging

fake = Faker()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

def generate_customer():
    return {
        "id": fake.uuid4(),
        "name": fake.name(),
        "phone": fake.phone_number(),
        "email": fake.email()
    }

def generate_dialogue(turns=40):
    # 40 turns ~ 10+ mins conversation
    customer_phrases = [
        "I noticed a suspicious charge on my account that I did not make.",
        "Can you help me? I think someone hacked my account.",
        "There are withdrawals I don't recognize.",
        "I want to report fraud on my credit card.",
        "My online banking was accessed without permission.",
        "I never authorized these payments.",
        "This transaction was not mine.",
        "Please freeze my account immediately.",
        "I fear identity theft is involved.",
        "Can you explain these charges?"
    ]
    bank_phrases = [
        "Thank you for contacting us. Please provide your account details.",
        "I am checking your transactions now.",
        "We will investigate this immediately.",
        "Please confirm the date and amount of the suspicious transaction.",
        "Your account has been temporarily frozen for your protection.",
        "We recommend changing your password immediately.",
        "Would you like to speak to a fraud specialist?",
        "We have flagged your account for unusual activity.",
        "Please monitor your account for further suspicious activity.",
        "Thank you for your patience while we resolve this."
    ]

    dialogue = []
    for i in range(turns):
        if i % 2 == 0:
            phrase = random.choice(customer_phrases)
            dialogue.append(f"Customer: {phrase}")
        else:
            phrase = random.choice(bank_phrases)
            dialogue.append(f"Bank Employee: {phrase}")
    return "\n".join(dialogue)
