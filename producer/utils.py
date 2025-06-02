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


def generate_dialogue(total_lines=300):
    if total_lines % 2 != 0:
        total_lines += 1

    scenarios = {
        "fraud": {
            "customer": [
                            "My account shows charges I didn't make!",
                            "I'm furious someone stole my card details.",
                            "You need to fix this now—I’m scared!",
                            "This is fraud and you're not doing enough!",
                            "Why aren't these reversed yet?",
                            "I trusted this bank—this shouldn't have happened.",
                            "I’m losing sleep over this. Fix it, please!",
                            "Every day this isn't resolved is agony.",
                            "How could this go unnoticed by your system?",
                            "You’re supposed to protect my money!",
                        ] + [
                            f"I feel completely violated by this fraud! #{i}" for i in range(1, 51)
                        ],
            "bank": [
                        "We're deeply sorry and will begin investigating immediately.",
                        "Your safety is our top priority—I'm freezing your account now.",
                        "You will not be held responsible for fraudulent charges.",
                        "We understand your fear, and we're acting fast.",
                        "I’ve escalated this to our fraud department.",
                        "Please know we take fraud cases very seriously.",
                        "You’ll receive an update within 24 hours.",
                        "We’re monitoring your account closely from now.",
                        "I’ll send a detailed report to your email now.",
                        "We understand how stressful this is—we’re with you.",
                    ] + [
                        f"We’re working closely with our fraud team on your case #{i}" for i in range(1, 51)
                    ]
        },
        "card_issue": {
            "customer": [
                            "My card keeps getting declined—it’s humiliating.",
                            "I lost my card and no one is helping!",
                            "Your ATM ate my card—I’m furious.",
                            "The chip on my card is not working anymore.",
                            "How do I even pay my bills without a card?",
                            "This is seriously affecting my day-to-day.",
                            "I feel stranded with no access to my funds.",
                            "This delay is completely unacceptable!",
                            "Why didn’t anyone tell me the card was expiring?",
                            "Do I need to switch banks to get proper service?",
                        ] + [
                            f"My card hasn't worked in days and it's ruining everything #{i}" for i in range(1, 51)
                        ],
            "bank": [
                        "I’m issuing a replacement immediately—no worries.",
                        "We apologize for the inconvenience, a card is on its way.",
                        "You can use virtual card access in the meantime.",
                        "We’ll reimburse any fees from the ATM issue.",
                        "You’ll have your new card within 2–3 business days.",
                        "I'm really sorry you’re experiencing this.",
                        "We’ve flagged your case as high priority.",
                        "We appreciate your patience—thank you.",
                        "I can walk you through setting up mobile payments.",
                        "Let me waive your monthly fee to make up for this.",
                    ] + [
                        f"We’ve expedited your replacement card request and will notify you shortly #{i}" for i in range(1, 51)
                    ]
        },
        "login_problem": {
            "customer": [
                            "I’ve been locked out of my account all day!",
                            "The app won’t recognize my face ID anymore!",
                            "I forgot my password and the reset isn't working!",
                            "I didn’t get my verification text—again!",
                            "Why do I have to call every time I can’t log in?",
                            "This is ruining my ability to manage my money.",
                            "I'm trying to pay bills and can't get in!",
                            "I’m beyond frustrated with this app.",
                            "Do you test the login feature at all?",
                            "I feel completely shut out of my finances!",
                        ] + [
                            f"I'm tired of being locked out every week. Fix this now! #{i}" for i in range(1, 51)
                        ],
            "bank": [
                        "Let me help you regain access immediately.",
                        "I’ve reset your login—try again now.",
                        "We’re upgrading security systems; I’m really sorry.",
                        "We’ll verify your identity and restore access.",
                        "Try using the desktop login while we fix the app.",
                        "I totally understand your frustration.",
                        "We’re fixing this with our IT team as we speak.",
                        "You’re not alone—we’re seeing this with others too.",
                        "We’re documenting this to prevent future issues.",
                        "Thank you for your patience—help is on the way.",
                    ] + [
                        f"Our engineers are prioritizing login errors like yours right now #{i}" for i in range(1, 51)
                    ]
        },
        "loan_application": {
            "customer": [
                            "Why was my loan denied? I have good credit.",
                            "I’m upset—I needed that loan for an emergency.",
                            "I submitted everything but haven’t heard back!",
                            "This delay is putting my plans at risk!",
                            "You promised a decision in 24 hours!",
                            "This is affecting my ability to relocate.",
                            "You’ve left me in limbo—I deserve an answer.",
                            "I feel ignored by your loan officers.",
                            "I’ve been a loyal customer—this is disappointing.",
                            "You said pre-approved—was that a lie?",
                        ] + [
                            f"My loan status is still unclear—this is causing major stress #{i}" for i in range(1, 51)
                        ],
            "bank": [
                        "I understand and I’ll look into your application personally.",
                        "We’ll prioritize your file and give you a clear update today.",
                        "I'm escalating this to the loan department manager.",
                        "We’re very sorry for the delay and stress this has caused.",
                        "I can help you explore other loan options right now.",
                        "We’re reviewing your documents again for reconsideration.",
                        "I will call you as soon as we get an update.",
                        "Let me schedule a follow-up with our credit team.",
                        "We really value your trust—we’ll make this right.",
                        "I’ll advocate for your case to move it forward faster.",
                    ] + [
                        f"Your application is under review again—we’ll keep you posted closely #{i}" for i in range(1, 51)
                    ]
        },
        "overdraft_fee": {
            "customer": [
                            "Why was I charged an overdraft fee?!",
                            "That $35 charge overdrew me even more!",
                            "I had money—your system is wrong!",
                            "I’m so angry about this unfair charge!",
                            "This is the third time this happened!",
                            "You’re charging me for your own delay!",
                            "This feels predatory—I’m not rich!",
                            "That one transaction ruined my budget.",
                            "I’m tired of calling about the same issue.",
                            "Please remove the charge—I’m begging you.",
                        ] + [
                            f"This overdraft ruined my week. I’m beyond upset #{i}" for i in range(1, 51)
                        ],
            "bank": [
                        "I understand—it looks like a timing issue, let me fix it.",
                        "We’ll waive the fee as a courtesy right now.",
                        "I see what happened, and I’m really sorry.",
                        "We’re reviewing this with our billing team.",
                        "I’ll refund the overdraft fee immediately.",
                        "Let me add a temporary buffer to prevent this again.",
                        "You're right—it shouldn't have happened.",
                        "I'll personally make sure this is corrected today.",
                        "This isn't the experience we want you to have.",
                        "We're issuing a goodwill credit to your account.",
                    ] + [
                        f"Our team is issuing a refund for the overdraft—thank you for your patience #{i}" for i in range(1, 51)
                    ]
        },
        "mobile_app_problem": {
            "customer": [
                            "Your app keeps crashing—it’s so frustrating!",
                            "I can’t deposit checks because of the app bugs!",
                            "I’m fed up with how unreliable the app is.",
                            "Why does it always freeze at login?",
                            "This app is ruining my banking experience!",
                            "Do you even test updates before releasing them?",
                            "The app update made things worse!",
                            "I’m switching banks if this continues.",
                            "It's unacceptable in 2025 to have these issues.",
                            "You said it was fixed last week—it's not!",
                        ] + [
                            f"I expect better from a major bank—this app issue is absurd #{i}" for i in range(1, 51)
                        ],
            "bank": [
                        "We’re rolling out a fix soon, thank you for your patience.",
                        "Let’s troubleshoot now—I want this resolved for you.",
                        "I’ll escalate this to our app support team right away.",
                        "We’re very sorry—it’s not the experience we want for you.",
                        "You can use the web version while we resolve this.",
                        "I understand this is affecting your experience deeply.",
                        "You deserve better, and we’re fixing it.",
                        "Thank you for bringing this to our attention again.",
                        "We’re submitting your case to engineering directly.",
                        "Our next release will address this—stay tuned.",
                    ] + [
                        f"Our engineers are working on a patch for this app crash #{i}" for i in range(1, 51)
                    ]
        },
        "wire_transfer": {
            "customer": [
                            "Where is my international wire? It’s been 5 days!",
                            "I’m panicking—those funds were urgent!",
                            "You told me it would be 24 hours!",
                            "I needed that money for my family overseas!",
                            "Why can’t anyone give me a straight answer?",
                            "This delay is putting everything at risk!",
                            "My recipient is in trouble because of this!",
                            "I feel like I’m being ignored here.",
                            "You said it was sent—where is it then?",
                            "I’m furious—this is unacceptable!",
                        ] + [
                            f"My money is missing and nobody seems to care #{i}" for i in range(1, 51)
                        ],
            "bank": [
                        "We’re investigating with the receiving bank immediately.",
                        "Your transfer was processed—we’ll track it down now.",
                        "I'm truly sorry—let’s find and resolve this fast.",
                        "You’ll receive a callback within the next hour.",
                        "We’re applying an urgent trace request for your transfer.",
                        "We’ve opened a case and assigned it top priority.",
                        "I'm monitoring this personally—I'll keep you updated.",
                        "You’ll get a confirmation as soon as we have answers.",
                        "This shouldn’t have happened—we take full responsibility.",
                        "We’re crediting your account a fee refund due to this.",
                    ] + [
                        f"We’ve launched a full trace with SWIFT—your case is urgent #{i}" for i in range(1, 51)
                    ]
        }
    }

    scenario_name = random.choice(list(scenarios.keys()))
    customer_lines = scenarios[scenario_name]["customer"]
    bank_lines = scenarios[scenario_name]["bank"]

    logging.info(f"Selected scenario: {scenario_name}")

    used_cust = []
    used_bank = []
    dialogue = []

    for i in range(total_lines):
        if i % 2 == 0:
            available = [l for l in customer_lines if l not in used_cust]
            if not available:
                used_cust = []
                available = customer_lines
            line = random.choice(available)
            used_cust.append(line)
            dialogue.append(f"Customer: {line}")
        else:
            available = [l for l in bank_lines if l not in used_bank]
            if not available:
                used_bank = []
                available = bank_lines
            line = random.choice(available)
            used_bank.append(line)
            dialogue.append(f"Bank Employee: {line}")

    return "\n".join(dialogue)


if __name__ == "__main__":
    customer = generate_customer()
    print(f"Customer Info: {customer}\n")
    print(generate_dialogue(300))
