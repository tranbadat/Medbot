# Open Problems — Family Group Chat Support

Difficult problems to solve before MedBot can support Telegram family groups (multi-member households sharing one chat with the bot and doctor).

## 1. Member discovery and identity mapping

Telegram bots cannot enumerate the full member list of a group unless the bot is promoted to admin, and even then `getChatMember` requires knowing the `user_id` in advance. There is no callback when someone joins quietly.

Implication: the system cannot auto-build the family roster. Each member must self-register (e.g. `/join <family_code>`) so we can map `telegram_user_id ↔ Patient`. Until they register, any message from them is from an unknown person and the bot must decide whether to ignore, prompt registration, or treat as a guest.

## 2. Multi-family ambiguity

A single Telegram user can belong to multiple family groups (e.g. their own household plus their parents'). When that user DMs the bot 1-1, the bot does not know which family context to use.

Implication: need an explicit context switcher (`/use_family <name>`) or default-family policy, plus per-message family tagging when in a group. Every downstream feature (appointments, reminders, history retrieval) must carry `(user_id, family_id)` rather than just `user_id`.

## 3. Per-speaker context for the LLM

Group history mixes many speakers. Feeding `[{role: user, content: ...}, ...]` directly to the LLM loses speaker identity, so the model cannot tell that "I had a fever yesterday" came from the mother, not the child.

Implication: history must be serialized with speaker labels (`Mother (35F): ...`, `Child A (8M): ...`), or each member's messages must be split into a separate logical session. Both approaches inflate token usage and complicate session boundaries — when does a "conversation" end if multiple people are talking concurrently?

## 4. Privacy and data leakage in shared chats

In a 1-1 chat, anything the bot or doctor says is private to one patient. In a group, every reply is visible to all members. Sensitive medical information (test results, mental health, reproductive health) leaking to other family members is a real harm, not a hypothetical one.

Implication: need a routing policy:
- Public-safe replies (clinic info, appointment confirmations) → group.
- Personal medical content → DM to the asker only, with a stub message in the group ("Đã trả lời riêng cho @user").
- Doctor must explicitly choose visibility for each reply. UI on the dashboard must surface this choice clearly and default to private.

## 5. Group spam vs. responsiveness

If the bot reacts to every message in the group, it becomes noise and the family will mute or remove it. If it only reacts to mentions, users forget to mention and feel the bot is broken.

Implication: need a hybrid trigger:
- Always respond to slash commands and direct mentions/replies.
- Optionally respond when the message is clearly a health question (LLM intent classifier returning high-confidence `health_question` or `sos`).
- Never respond to chit-chat between family members.

This requires the intent classifier to also output a "should the bot speak up" decision, not just a label. False positives are worse here than in 1-1.

## 6. Doctor handoff in a group setting

Today, when AI escalates to a doctor, the doctor's replies are relayed back into the same chat. In a group that means the doctor effectively joins the family chat. Issues:
- The doctor sees prior unrelated family chatter in history.
- Other members can interject mid-consultation, derailing the case.
- Billing and accountability: which member is the "patient" for this case?

Implication: when escalating from a group, the system should fork the conversation into a private thread (DM between bot and asker, with doctor relayed in there), and post a status stub back to the group. This breaks the "one chat, never switches" invariant from the original spec — needs a deliberate exception.

## 7. Schema migration with live sessions

Current `Patient` and `Session` tables key on `telegram_chat_id` (a 1-1 assumption). Adding `Family` and `FamilyMember` requires changing the unique constraints and rewriting every query that resolves a patient from a chat_id. There are live appointments and reminders pinned to the old `telegram_chat_id` — they must keep working during and after migration.

Implication: backfill strategy needed:
1. Add nullable `family_id` and `tg_user_id` columns.
2. For every existing Patient, create a single-member family.
3. Switch reads to the new `(chat_id, user_id)` lookup but keep the old path as fallback for one release.
4. Drop the old unique constraint last.

## 8. Reminders and notifications addressed to a specific person

Medicine reminders today fire to a chat. In a group, the reminder must `@mention` the right person, otherwise it is ignored. Telegram mentions require either a `@username` (not all users have one) or a `tg://user?id=...` markdown link. Both need the user's `tg_user_id`, which we may not have if they joined the family by code rather than by talking to the bot in the group.

Implication: enforce that a member is only "active" in a family after the bot has seen at least one message from them in the group (so we capture their `tg_user_id`). Until then, reminders fall back to DM.

## 9. Zalo parity

Zalo Official Account does not support group chat in the way Telegram does. Family features will be Telegram-only for the foreseeable future, splitting the product surface across platforms.

Implication: feature flag the entire family subsystem on platform. Documentation, UX copy, and dashboard filters must make clear which capabilities are platform-specific so users don't expect parity.

## 10. Consent and minors

Family groups will frequently include children. Storing health data for minors raises consent issues (who can register them, who can see their data, when they age out, right to be forgotten).

Implication: need an explicit guardian relationship in the schema, age-gated visibility rules, and a consent capture step at registration. This is as much a legal/ops problem as a technical one and should be reviewed with whoever owns compliance for the clinic before any code is written.

---

## Suggested phasing

1. Schema groundwork: `families`, `family_members`, dual-key lookups, migration of existing patients into single-member families.
2. Identity layer: family resolver added as Layer 0.5 in the message pipeline; per-message `(family_id, member_id)` propagation.
3. Group bot mode: mention/command-only triggers, classifier-gated proactive replies, per-speaker history labeling.
4. Privacy routing: DM-vs-group reply policy; doctor dashboard visibility controls.
5. Forked doctor handoff: private thread for consultation, group stub for status.
6. Reminder addressing: `@mention` with DM fallback.
7. Consent and minors: guardian model, age gating, audit log.
