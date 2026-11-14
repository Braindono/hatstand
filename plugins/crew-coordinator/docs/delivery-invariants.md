# Delivery invariants (crew-coordinator 0.26.0)

What must happen to a message, by kind, recipient state and reply shape. `tests/test_c260_delivery_matrix.py` asserts every row below over the cross product; a row the code breaks is a bug. Rows marked CHOICE are decisions for the operator.

## 1. Words

- **Delivered:** the mail is in the recipient's inbox. Always true, for every kind and state. A role address reaches the live holder (a superseded chat's id reaches its successor); a vacant role keeps the mail for the next holder.
- **Ring:** the send result carries a `nudge` with one fixed-text instruction for the sender: SendMessage to the holder's chat, or run its wake routine. The server rings nobody itself.
- **Retired chat's id:** the agent id of a chat that retired with no successor and no role. A send to it is delivered to an inbox nobody will read; for covered mail the sender is told (a counted miss), for uncovered mail nothing is said.
- **Handed-off chat's id:** the agent id of a chat that handed its role off and has not been restored. A send to it by id waits for the restore; for covered mail the sender is told ("queued for the next restore; miss counted", the same wording as a vacant role), for uncovered mail nothing is said. A send by role name to the same chat is judged as a vacant role (one miss, never two).
- **Counted miss:** one `nudge.miss` record per mail and recipient for covered mail that no ring and no relay can carry. It is an audit and report record, and the send result names it.
- **Doorbell error:** if the doorbell code itself fails while handling a send, the send still succeeds and every covered recipient counts a miss with the reason `doorbell_error` (best effort); nothing is swallowed silently.
- **Relay:** when the harness cap skips a ring, a stale mark or a spent cold-wake slot closes the route, or the sender never reports a ring, a live local holder is asked to ring for the sender. If none can, a counted miss is recorded.
- **Rewake:** a ring reported delivered whose mail is still unread 15 minutes later (then 1 hour) is rung again.
- **Alarm:** offered, held or route-closed mail still unread after the alarm delay raises one alarm to the sender. At most one alarm per role per hour (the others follow in the next hour, and the next alarm counts the suppressed ones).
- **Mail only:** no ring, no relay, no rewake; the mail waits for the recipient's next prompt or start.
- **Ask:** a task, question or review, or any mail (of any kind) sent with expects_reply. An ask is owed until answered.
- **Open ask:** an ask whose task is not finished, that the recipient's role did not dismiss (owed_close), and that the sender has not answered with a result or handoff. An acknowledgement ("on it": a message or notice) never closes it.
- **Waiting:** the recipient has an open ask that this mail answers: reply_to it, or on the same thread, or the mail cites it in refs.
- **Covered mail** (the safety net): an ask; a result or handoff that answers an open ask by waiting; a message that replies (reply_to) to an open ask. Every covered mail ends with a ring, a relay or a counted miss, and is rewoken or alarmed if unread. This is the class rule: no covered mail is ever left with only "mail only".
- **Uncovered mail:** a notice, a message that is not an ask or a direct reply to one, a result or handoff nobody waits for. Rung where cheap (warm chat), never relayed or rewoken.

## 2. What a send does

| Mail | Warm chat | Cold chat (last call over 1 h) | Wake routine only | Capped (pair, sender or global) | Route closed (stale mark) | No route at all | Retired chat's id (no successor) | Handed-off chat's id | Vacant role |
|---|---|---|---|---|---|---|---|---|---|
| Ask (task, question, review, or expects_reply on any kind) | ring | ring | ring | relay or counted miss | relay or counted miss, alarm | counted miss, shown in the send result | counted miss, shown in the send result | "queued for the next restore", counted miss | "queued for the next restore", counted miss |
| Result, handoff or message answering an open ask (reply_to, thread, ref; a message only by reply_to) | ring | ring | ring | relay or counted miss | relay or counted miss, alarm | counted miss | counted miss | as above, counted miss | as above, counted miss |
| Result or handoff nobody waits for (or the ask is answered, finished or dismissed) | ring | result: mail only; handoff: ring (once per 30 min) | ring (once per 10 min) | skipped, no relay | mail only | mail only | mail only | nothing said | queued for the next restore |
| Notice, or a message that is not an ask or a direct reply | none | none | none | none | none | none | none | none | nothing |

Further rules:
1. **Hold (per recipient, any kind).** A mail that would ring like an ask is held back, with the reason "rung under 60 s ago", when an earlier answer-kind mail to the same recipient was rung less than 60 seconds ago and is still unread: one ring brings the chat to its inbox, which lists both. This holds whatever the kind of the later mail. A held mail has no offer of its own; it is protected by the first ring (its rewake or relay) and by the alarm, which reads every held mail as unread offered mail. Mail that does not ring like an ask (a notice, an uncovered result) is never held.
2. **Reply rings.** A reply to an open ask rings a cold chat, and so does every acknowledgement sent as a reply_to message: an "on it" answers an ask, so it rings the asker once. This is the accepted trade-off of the 0.26.0 safety net (CHOICE C5 below). An acknowledgement never closes the ask: the real result still rings.
3. **Several recipients.** One instruction text, one report per recipient, each with its own key (session id, or the first 8 characters of the agent id for a wake-routine recipient). One recipient's report never hides another's missing report or skip. **Each recipient is judged on its own row of the table, whatever the others are**: a ring for one never hides a counted miss, a relay or a skip for another, and a vacant role, a chat with no route or a retired chat's id in the same send still counts its own miss when the mail is covered. One waiting and one not are judged separately.
4. **Operator and system mail** start no ring. Operator mail is never cut, and is never dismissed with owed_close. Operator tasks and questions are owed.
5. **Superseded chats.** A send to the agent id of a superseded chat reaches its successor and rings it. A reply to an ask sent by the recipient's predecessor is a reply to an open ask of the same role.
6. **Cold-wake slot.** A cold chat is woken by id at most once per 30 minutes for mail that is not covered (a handoff nobody waits for); a covered mail ignores the slot but uses it. So a handoff sent to a cold chat less than 30 minutes after any wake of it is mail only: the chat was woken and reads both.
7. **The send result names every recipient's outcome, from one place.** For every recipient of a send, the send result names exactly the outcome recorded for it: a ring, a relay request, a counted miss with its reason, a hold, or mail only. One function builds the list from the records actually written for that message (`nudge.offered`, `nudge.skipped`, `nudge.relay_offer`, `nudge.miss`) and the result carries it as `nudge_outcomes` (one entry per recipient: who, outcome, reasons); the older fields (`nudge`, `nudge_skipped`, `nudge_mail_only`) never leave out a recipient that has a record. A failure inside the doorbell is judged with the same covered rule as the normal path (when the judgement itself fails, the mail counts as covered) and the result says "miss (doorbell_error)".
8. **The backstop scan treats each recipient independently.** When the sender never reports the ring of a covered send to several recipients, every recipient that has not read the mail gets its own relay request or counted miss after the silence delay, not only the first. Every backstop record and lookup (relay offer, relay closed, miss, alarm) is keyed by (message, recipient). (The 15-minute and 1-hour rewake is still made for the first recipient only: CHOICE C8 below.)

## 3. Read, owed, cut

| Rule | Must hold |
|---|---|
| Read | Mail stays unread until the recipient lists it in `harness_inbox` (not a peek), recalls it whole, or answers it with reply_to. A listing cut off by size leaves the unshown mail unread. |
| Owed | Asks are owed until answered. Any later message of the recipient on the thread clears the recipient's owed entry; only a result or handoff closes the asker's wait. `harness_admin op=owed` lists every owed id; the operator's asks come first, newest first. |
| Cut | A notice, result or message over 1,000 characters shows its first 600 and a pointer outside the untrusted fence, unless it is an ask (expects_reply) or from the operator. It stays unread at the first listing and is read at the second when no ask of the recipient waits on it. Task, question, review, handoff, expects_reply mail and operator mail are never cut. |
| Rewake, relay, alarm | Only for covered mail (section 1). |
| Listing size | One `harness_inbox` listing holds whole mails up to 10,000 characters (50,000 with full=true). Mail past the limit stays unread and is counted ("N more not shown"); one mail longer than the limit by itself is shown cut and stays unread. Covered by `tests/test_c260_round6.py`, not by the matrix. |

## 3b. What the matrix does not cover

Live app behaviour: the app's cross-session send cap, RemoteTrigger runs and Cowork chats are outside the tests, which run in one process. The matrix shows what the harness returns and records, not that the app delivered a ring.

## 4. Choices for the operator

- **C1 (cosmetic).** A notice to a live chat says "starts no wake"; a notice to a vacant role says nothing. Recommend: leave.
- **C2.** A plain message that only cites an open ask by ref (not reply_to) does not ring; a result or handoff that cites it does. Recommend: leave (reply_to is the documented answer).
- **C3.** A result to a cold chat that waits on nothing is mail only (a handoff rings it). Decided earlier.
- **C4 (decided in round 7).** A message or notice with expects_reply is an ask: same ring, relay and rewake as a question.
- **C5.** An acknowledgement sent as a reply_to message rings the asker (it answers an ask). Alternative: an acknowledgement does not ring. Recommend: leave; the cost is one ring per acknowledgement.
- **C6 (decided in round 7).** Covered mail to a recipient with no route at all (a chat with no session id and no wake routine, on another machine, or a vacant role) counts a miss (`nudge.miss`, shown in the send result and the weekly report). The alarm cannot raise it: an alarm goes to a chat that has a session, and there is none. The mail still waits in the inbox.
- **C8 (new).** The rewake (15 minutes, then 1 hour) of a delivered-but-unread ring is made for the first recipient of a several-recipient send only; the relay for a silent sender is made for every recipient. Alternative: rewake every recipient. Recommend: leave (a rewake needs a per-recipient wake key, which the ledger does not carry yet).
- **C7 (new).** A handoff to a cold chat within 30 minutes of any wake of that chat is mail only (uncovered). Alternative: treat a handoff as covered. Recommend: leave.

## 5. Known limits (0.26.0)

Found by the foresight review and left for the delivery redesign after the 0.26.0 stop; none of them is covered by the matrix.

- **B. Several cover predicates.** "Covered" is decided in several places and at several times (send, scan), and with two kinds of identity (lineage and role): a new holder of a carry role is not in the asker's lineage, a task finished after the ring uncovers the mail for the scan, and a result covered through a wake routine is not covered at send time once the trigger slot is spent.
- **C. State change between send and scan.** A recipient that hands off, retires or leaves the role after the ring is judged by the send-time row only; a relay or rewake can ring a dead chat and no miss is counted.
- **D. A thread with several asks.** An answer to one ask closes every open ask of the answerer on that thread for the wake backstop.
- **E. Scan clocks and windows.** The backstops run only inside a harness call and only inside fixed windows; outcomes written after the send result reach no live party but the ledger and the weekly report; an alarm goes to the recipient's own chat, only to a chat with a local session active in the last 30 minutes.
- **F. Decisions not recorded.** A crash between the message and its doorbell records, a failed skip record, or a slot spent before the offer is written leaves no record for any scan; there is no reconciler over the sent messages. (A failing miss for a vacant role after another recipient rang is now retried as `doorbell_error`.)
- **G. Operator settings.** With the doorbell off, or a role muted in operator.json, a covered task ends with a skip entry only: no relay and no counted miss.
- **H. Address fan-out.** Groups, the broadcast address and a chat reached by two address forms (id and role) are not judged once per recipient key.
- **I. A stale_id report on a cold chat.** A "skipped stale_id" report on a covered task to a cold recipient with no wake routine gives no relay, no counted miss and no alarm.
- **J. A not-needed report on an answer kind.** A "skipped not needed" report on an expects_reply message or a covered result gives no relay and no counted miss, contrary to C4.
