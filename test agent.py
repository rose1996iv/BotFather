from agent import ask

questions = [
    "ဝင်ခွင့်လျှောက်ရန် ဘာစာရွက်စာတမ်းများ လိုအပ်သလဲ?",
    "Computer Science သင်တန်းကြေးသည် ဘယ်လောက်ကျသလဲ?",
    "Nursing program အတွက် သတ်မှတ်ချက်များကား အဘယ်နည်း?",
]

for q in questions:
    print(f"\nမေးခွန်း: {q}")
    print(f"အဖြေ:   {ask(q)}")
    print("-" * 60)