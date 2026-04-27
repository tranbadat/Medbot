# MedBot — Luồng xử lý tin nhắn người dùng

## Tổng quan các lớp

```mermaid
flowchart TD
    A[User text] --> B[Layer 0: Transport<br/>Telegram / Zalo webhook]
    B --> C[Layer 1: Pre-dispatch<br/>ConvHandler · Slash · Regex]
    C --> D[Layer 2: Onboarding gate<br/>welcome / profile]
    D --> E[Layer 3: Deterministic shortcuts<br/>menu · lich · appointment kw]
    E --> F[Layer 4: LLM Intent Classifier]
    F --> G[Layer 5: Conversational AI<br/>RAG + Claude/OpenAI]
    G --> H[Layer 6: Reply render]
    H --> I[Layer 7: Persist + side effects]
```

## Thuật toán quyết định

```mermaid
flowchart TD
    Start([msg]) --> Conv{In active<br/>ConvHandler?}
    Conv -- yes --> ConvFlow[continue flow]
    Conv -- no --> Cmd{Slash command?}
    Cmd -- yes --> CmdRun[run command]
    Cmd -- no --> Onb{Need onboarding?}
    Onb -- yes --> Welcome[show welcome / profile]
    Onb -- no --> Norm[normalize text]

    Norm --> Menu{in MENU_KEYWORDS?}
    Menu -- yes --> ShowMenu[show main menu]
    Menu -- no --> Lich{== 'lich' ?}
    Lich -- yes --> Disamb[3 buttons:<br/>Lich kham · Nhac thuoc · Menu]
    Lich -- no --> Med{mentions thuoc / nhac?}

    Med -- yes --> CLF1[LLM classify]
    Med -- no --> Appt{appointment kw?}
    Appt -- yes --> ApptList[show appointments]
    Appt -- no --> CLF2[LLM classify]

    CLF1 --> Disp{intent?}
    CLF2 --> Disp
    Disp -- medicine_list --> RList[show reminders]
    Disp -- medicine_add --> RAdd[btn add reminder]
    Disp -- appointment_view --> ApptList
    Disp -- appointment_book --> ABook[btn book]
    Disp -- clinic_info --> Info[clinic card]
    Disp -- sos --> SOS[SOS card]
    Disp -- call_doctor --> Doc[doctor carousel]
    Disp -- menu --> ShowMenu
    Disp -- health_question / other / low_conf --> AI[Layer 5: AI pipeline]
```

## Layer 5 — Conversational AI pipeline

```mermaid
flowchart LR
    In([user msg]) --> Sess[get/create session]
    Sess --> DocGate{doctor assigned?}
    DocGate -- yes --> Relay[relay to doctor WS<br/>type=forwarded_to_doctor]
    DocGate -- no --> Regex{regex_check<br/>out-of-scope?}
    Regex -- hit --> ReqDoc[request_doctor]
    Regex -- miss --> Ctx[history + RAG + online doctors]
    Ctx --> LLM[Claude / OpenAI]
    LLM --> Parse{JSON action=request_doctor?}
    Parse -- yes --> ReqDoc
    Parse -- no --> Reply[type=ai_reply]
```

## 3 lớp phòng thủ out-of-scope

```mermaid
flowchart LR
    M[user msg] --> R1[1 · Regex cứng<br/>OUT_OF_SCOPE_PATTERNS]
    R1 -- pass --> R2[2 · System prompt<br/>Claude tự phán quyết JSON]
    R2 -- pass --> R3[3 · Dispatch<br/>request_doctor carousel]
    R1 -. hit .-> D[Doctor handoff]
    R2 -. hit .-> D
    R3 --> D
```

## Pseudocode

```python
def handle_user_text(text, ctx):
    if in_conversation_flow(ctx):  return route_to_flow()
    if is_command(text):           return route_command()
    if onboarding_required(ctx):   return show_onboarding()

    t = normalize(text)
    if t in MENU_KEYWORDS:         return show_menu()
    if t in LICH_DISAMBIG:         return ask_lich_type()

    if mentions_medicine(t):
        if intent := classify(text):     # LLM, bypass keyword bias
            return dispatch(intent)
    else:
        if appointment_keyword(t):       return show_appointments()
        if intent := classify(text):     return dispatch(intent)

    # Health Q&A fallback (Layer 5)
    if regex_out_of_scope(text):         return request_doctor()
    ctx_text = rag_search(text) + online_doctors_if_relevant(text)
    reply = llm_chat(history + [text], system + ctx_text)
    if json := parse_request_doctor(reply):
        return request_doctor(json)
    return ai_reply(reply)
```

## Bảng nhãn intent (Layer 4)

| Intent | Hành động |
|---|---|
| menu | show_welcome |
| appointment_view / appointment_cancel | _handle_appointment_query |
| appointment_book | btn bk:start |
| medicine_list | show_reminders |
| medicine_add | btn med:new |
| clinic_info | _show_clinic_info |
| sos | _show_sos |
| call_doctor | show_out_of_scope_cta |
| health_question / other | fall through → Layer 5 |

## Đặc điểm thiết kế

- Keyword chỉ làm shortcut rẻ và chắc chắn; mọi câu mơ hồ → LLM classifier.
- Tin nhắn chứa `thuốc/nhắc` luôn đi qua classifier để tránh nhầm câu hỏi y tế thành lệnh nhắc thuốc.
- Classifier tách biệt: prompt riêng, `max_tokens=60`, `temperature=0`.
- Doctor takeover tuyệt đối: bot im lặng khi session đã gán bác sĩ.
- 3 lớp phòng thủ out-of-scope: regex → system prompt JSON → dispatch.
