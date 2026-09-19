# Deadlock (appid 1422450) — programmatic access to TEXT CHAT

Scope: read incoming chat / send chat, no memory reading, no injection, no protocol spoofing.
(Valve wiki pages were retrieved by solving the site's Anubis proof-of-work challenge locally; `List_of_Deadlock_console_commands_and_variables` and `Command_line_options` were both fetched in full.)

Evidence base: web sources **plus** the locally installed retail build (`D:\software\steam\steamapps\common\Deadlock`, `ClientVersion=6689`, `SourceRevision=10988735`, `VersionDate=Sep 11 2026`, game dir `citadel`).

## 1. Console commands — CONFIRMED exists, CONFIRMED unusable as a chat API

The [Valve wiki Deadlock cvar dump](https://developer.valvesoftware.com/wiki/List_of_Deadlock_console_commands_and_variables) (retrieved 2026-04-12, build 10725) lists:

- `say` — cmd, flags **`sv`**, "Display player message"; `say_team` — cmd, flags **`sv`**, "Display player message to team".
- `say_chat` / `say_chat_team` — cmd, flags `cl, release`, "Opens chat menu to chat with everyone / with Allies" ⇒ UI menu openers, not text senders.
- `+chatwheel`, `-chatwheel`, `+herochatwheel`, `chatwheel_pingwheel`, `in_ability_ping`; `deadlock_chat_mode`; `team_chat_auto_join`; `sv_allchat`; `tv_nochat`; `tv_showallchat`.
- **No `messagemode`, `messagemode2`, `cl_chat*`, `con_logfile`, `condebug`, `netcon` anywhere in the list.** `sv_cheats` exists but only works in cheat-enabled private lobbies.

A fuller in-game `cvarlist log` dump already present in this workspace (`_dlk/commands.txt`, `_dlk/convars.txt`, dated 2026-09-12) adds: `say (gamedll client_can_execute)`, `say_team (gamedll client_can_execute)` — i.e. the engine flags them executable by the client, even though the shipped bug report says chat binds do not work; **whether they actually send is UNVERIFIED and needs an in-game test.** Same dump also shows `chat_fake_player_say_all <player_slot> <message>`, `chat_fake_player_say_allies`, `chat_fake_quick_response` (all `developmentonly clientdll` — local display only, not a send), `citadel_send_text_chat_to_player_pings`, `citadel_enable_chat_rate_limiting`, and UI cvars `chat_max_messages`, `citadel_chat_fade_time`.

CONFIRMED behaviour: [`say` does not work — reported as a bug 2025-08-20](https://forums.playdeadlock.com/threads/say-console-command-doesnt-work.75914/). CONFIRMED structural limit: [the console is usable only in Hideout / Sandbox / Explore NYC / cheat-enabled customs, and `bind` is largely defunct](https://deadlock.wiki/Console_commands) ([bind bug report, 2026-01](https://forums.playdeadlock.com/threads/key-assignment-via-bind-command-does-not-work.102282/)).

## 2. Remote console / netcon — EXISTS in the engine; NOT verified for Deadlock

- `-netconport <port>` + `-netconpassword` are documented for **Source 1-era games since Left 4 Dead** (["Creates a remotely accessible server console … telnet …"](https://developer.valvesoftware.com/wiki/Command_line_options)); no Source 2 or Deadlock statement exists, and `-netcon`/`-netconip` are not documented at all on that page.
- Local binary evidence: `game\bin\win64\engine2.dll` contains `CNetConsoleMgr` and `"Unable to open netconsole on port %d"`; `vconsole2.exe` + `vconcomm.dll` ship with the game (`CVConsoleLoggingListener`, cvars `vcon_clients`, `vcon_clear_buffered_log`).
- **Protocol is NOT plain text.** VConsole2 = binary chunk stream over TCP (12-byte header: 4-char type, `0x00d20000`, length, handle) — [VConsoleLib](https://github.com/Penguinwizzard/VConsoleLib), [CS2RemoteConsole `libvconsole`](https://github.com/theokyr/CS2RemoteConsole). Chunk types: receive `PRNT/CHAN/AINF/ADON/CVAR/CFGV`, send `CMND` ⇒ reads output **and** executes commands; no auth seen in either implementation. Default TCP port 29000. Public Python port: [VConsoleLib.python](https://github.com/uilton-oliveira/VConsoleLib.python).
- CS2RemoteConsole requires CS2 in `-tools` mode and defaults to `127.0.0.1:29000`. In CS2, `-netconport` on Windows [fails with `WSANOTINITIALISED` unless `-tools` is set](https://github.com/ValveSoftware/csgo-osx-linux/issues/3603) (issue still open, last activity 2026-07). **No Deadlock evidence either way.**

## 3. Console logging — `-condebug` looks absent; chat-echo UNVERIFIED

- `-condebug` + `-conclearlog` (→ `console.log`) are documented generically ([command line options](https://developer.valvesoftware.com/wiki/Command_line_options)) and CONFIRMED in CS2: bot projects parse `[ALL]`/`[TEAM]` lines out of `…\Counter-Strike Global Offensive\game\csgo\console.log` ([CS2-Ai-Chatter](https://github.com/drippycatcs/CS2-Ai-Chatter), [chat-strike](https://github.com/handle1337/chat-strike)).
- Deadlock: `engine2.dll` contains **`-con_logfile`** and `con_logfile_suffix`, but **no `-condebug` string in `engine2.dll`/`tier0.dll`**; the in-game dump has `log` and `condump` as *release*-tagged commands but **no `con_logfile` cvar** (only `con_logfile_suffix`, devonly-internal); no `console.log` exists in the install dir despite a session today; the Valve wiki itself notes Deadlock ["does not print the actual cvar list using `Cvarlist` when using `-condebug` like previous games did"](https://developer.valvesoftware.com/wiki/List_of_Deadlock_console_commands_and_variables). **No Deadlock chat-in-console excerpt exists anywhere I could find** — this is the single biggest open question for a log-tail approach. Path if it works: `…\steamapps\common\Deadlock\game\citadel\console.log` ([directory layout](https://www.source2.wiki/Basics/working-on-content/directory-layout)).

## 4. GC / protobuf — CONFIRMED chat is GC/protobuf; no official third-party API

From the community re-hosts of shipped protos ([SteamTracking/Protobufs `deadlock/`](https://github.com/SteamTracking/Protobufs), `master`, pushed 2026-09-11):

- In-match: `CCitadelClientMsg_ChatMsg` (`CITADEL_CM_ChatMsg = 1005`; `chat_text`, `all_chat`, `lane_color`) → broadcast `CCitadelUserMsg_ChatMsg` (`k_EUserMsg_ChatMsg = 314`). Chatwheel: `CCitadelUserMsg_ChatWheel`.
- Party chat via Game Coordinator: `CMsgClientToGCPartySendChatMsg` (9277), `…Response` (9278), `CMsgGCToClientPartyChatMsg` (9279). Its result enum matches the shipped strings **exactly**: `Citadel_ChatError_{Timeout,InternalError,InvalidPermission,Disabled,RateLimited,InvalidMsg,Unknown}` in `game\citadel\resource\localization\citadel_main\citadel_main_english.txt` (also `Citadel_ChatTarget_GameAll/GameAllies/Party`, `Citadel_ChatSender_LocalClient`) — **local-build confirmed**.
- Official side: [`ISteamGameCoordinator` is documented](https://partner.steamgames.com/doc/api/ISteamGameCoordinator) but explicitly **"largely deprecated"** and it has **no global accessor** (`isteamclient.h`/SteamClient023 has no `GetISteamGameCoordinator`); it only lets your own app talk to its own GC. Nothing official exposes Deadlock's GC; using these protos yourself = session impersonation (excluded). Protos here are community re-hosts, not Valve publications.

## 5. Panorama — no external-process interface found

Deadlock ships `panorama.dll`/`panoramauiclient.dll` (`PanoramaUIEngine001`, `GameUIService_001`), cvars `panorama_toggledebugger_mode`, `panorama_debug_overlay_opacity`, `panorama_console_position_and_size`, commands [`dump_panorama_events`, `dump_panorama_css_properties`](https://developer.valvesoftware.com/wiki/List_of_Deadlock_console_commands_and_variables). These are in-game debugger tools only; **no documented IPC, socket, or file bridge lets an external process read Panorama panel text** (UNVERIFIED, but nothing found). Chat's *assets* are present in `pak01_dir.vpk` (`ui_chat_msg_received_01..06`, `chat_type_teamchat/partychat/disabled`, `chat_bubble_speaker_arrow`, `hudchat_mask`), confirming a Panorama chat panel exists, but the layout XMLs themselves are inside the VPK pack and I could not read them. Mods in Deadlock are asset/VPK overrides via `gameinfo.gi` ([Mod Manager docs](https://docs.deadlockmods.app/modding)) — they cannot read chat either.

## 6. Existing tools

- **No Deadlock text-chat reader or sender found.** [RedMser/ChatLane](https://github.com/RedMser/ChatLane) only generates chat-wheel configs. The one adjacent tool, [KevinPequad/deadlock-linux-dictation](https://github.com/KevinPequad/deadlock-linux-dictation) (2★), uses the keyboard-injection route to *put* text into the chat box — precedent for the "send" recommendation in §7.
- Real-time read DOES exist server-side: [deadlock-api live-events](https://github.com/deadlock-api/deadlock-api) streams an ongoing match's demo over SSE, with query param `subscribed_chat_messages` ("Include in-game chat messages"). deadlock-api is otherwise stats/match-history.
- [Rupas1k/source2-demo](https://github.com/Rupas1k/source2-demo) parses Deadlock chat out of recorded demos (`dl-examples/chat`, `CCitadelUserMsgChatMsg`) — replays only, not live.

## 7. Verdict (legitimate options)

**Read:** 1) OCR of the chat panel — always available; needs in-game verification. 2) SSE `subscribed_chat_messages` — documented real chat, spectated matches only. 3) Tail `game\citadel\console.log` behind `-con_logfile` — most direct if it works; **needs in-game verification** (flag *and* chat echo).
**Send:** only OS-level synthetic keyboard input (chat key → type/paste → Enter). Every in-game programmatic path is closed.
**Avoid (you excluded them):** VConsole/netcon without `-tools`, GC proto replay, memory/injection.
**Unverified:** `say`/`say_team` executability in-game; `-netconport` on Windows without `-tools`; whether Deadlock's VConsole2 accepts the CS2 handshake; `-con_logfile` behaviour and chat echo; Panorama external access.
