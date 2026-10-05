# Shadow Control Chat

A terminal-based chat and file-sharing application built with Python's standard library. A multithreaded TCP server handles user accounts, private messages, and file transfers, while an interactive client receives messages and transfers in the background.

Built as a Computer Networks course project to explore socket programming, message framing, and the separation of control commands from application data over one TCP connection.

## Features

- Register, log in, log out, and list online users.
- Send private messages to registered users.
- Queue messages for offline users and deliver them when they log in.
- Upload files to a personal directory on the server.
- List uploaded files and request to share them with an online user.
- Accept or reject incoming file-share requests.
- Transfer binary files in 1 KB chunks with client-side progress output.
- Record chat traffic in a server-side history file.

## Requirements

Python 3.6 or newer. No third-party packages are required.

## Quick start

```bash
git clone https://github.com/ashkanchaji/Shadow_Control_Chat.git
cd Shadow_Control_Chat
python3 server.py
```

Leave the server running. In another terminal, open a client from the repository directory:

```bash
python3 client.py
```

Open another terminal and run the same client command to try chatting between two users. Wait for each server response before entering the next command.

In the first client:

```text
REGISTER alice demo_alice_password
LOGIN alice demo_alice_password
```

In the second client:

```text
REGISTER bob demo_bob_password
LOGIN bob demo_bob_password
```

Then, in Alice's client:

```text
LIST_USERS
CHAT bob Hello from Alice!
```

Bob receives the message asynchronously. To try offline delivery, log Bob out, send another message from Alice, and log Bob back in. Offline messages remain available only while the server process is running.

### Share a file

The client creates `client_files/` automatically. Place a small file, such as `notes.txt`, inside it. In Alice's client:

```text
UPLOAD notes.txt
LIST_FILES
SHARE notes.txt bob
```

Wait for upload completion before sharing. In Bob's client, respond to the share request:

```text
ACCEPT notes.txt
```

The download is saved to Bob's `client_files/` directory. Use `REJECT notes.txt` to decline instead. For a local demonstration, clients started from the same directory share the same local file folder; run each client from a separate working directory if you want separate folders.

## Client commands

Commands are case-insensitive; usernames, passwords, and filenames retain their case.

| Command | Description |
| --- | --- |
| `REGISTER <username> <password>` | Create an account for the current server session. |
| `LOGIN <username> <password>` | Authenticate and receive queued messages. |
| `LOGOUT` | Log out while keeping the connection open. |
| `LIST_USERS` | List currently logged-in users. |
| `CHAT <username> <message>` | Send a private message or queue it for an offline user. |
| `UPLOAD <filename>` | Upload a file from `client_files/`. |
| `LIST_FILES` | List files in your server-side directory. |
| `SHARE <filename> <username>` | Offer an uploaded file to an online user. |
| `ACCEPT <filename>` | Accept an incoming file-share request. |
| `REJECT <filename>` | Reject an incoming file-share request. |
| `EXIT` | Disconnect and close the client. |

Use simple usernames and filenames without spaces, `|`, or path separators. Passwords must not contain spaces or `|`.

## Configuration

Configuration lives in constants near the top of each script:

| Script | Setting | Default | Purpose |
| --- | --- | --- | --- |
| `server.py` | `HOST` | `0.0.0.0` | Listen on all IPv4 interfaces. |
| `server.py` | `PORT` | `8888` | TCP listening port. |
| `server.py` | `BASE_DIR` | `server_files` | Uploaded files and chat history. |
| `server.py` | `MAX_FILE_SIZE` | `10 * 1024 * 1024` | Maximum declared upload size: 10 MiB. |
| `client.py` | `HOST` | `127.0.0.1` | Server address. |
| `client.py` | `PORT` | `8888` | Must match the server port. |
| `client.py` | `CLIENT_DIR` | `client_files` | Local upload and download folder. |

For a trusted LAN demonstration, set the client's `HOST` to the server's LAN address and allow TCP port `8888` through the server's firewall. All data directories are relative to the working directory and are created automatically.

## How the protocol works

Each message has a four-byte unsigned length prefix in network byte order (`struct.pack('!I', length)`), followed by the payload. The receiver reads exactly the indicated number of bytes, so messages can span multiple TCP reads.

Payloads distinguish control traffic (`CTRL`) from chat and file data (`DATA`):

```text
CTRL|REGISTER|username|password
CTRL|LOGIN|username|password
CTRL|UPLOAD|filename|filesize
CTRL|SHARE|filename|target_user
DATA|CHAT|target_user|shifted_message
DATA|FILE_CHUNK|filename|chunk_index|chunk_size|<raw bytes>
DATA|END_FILE|filename
```

For uploads, the client waits for `UPLOAD_ACK`, sends chunks of up to 1,024 bytes, and finishes with `END_FILE`. The server replies with `UPLOAD_SUCCESS`. For sharing, the recipient receives a `SHARE_REQUEST`; accepting it causes the server to stream the sender's stored file to the recipient.

The server starts a thread per connection and a separate thread for each accepted download. The client uses a background receive thread and upload threads so incoming traffic can appear while the command prompt is active.

## Repository contents

```text
Shadow_Control_Chat/
├── client.py       # Interactive TCP client
├── server.py       # Multithreaded TCP server
├── README.md
└── .gitignore
```

At runtime, the application creates:

```text
client_files/                  # Local uploads and received files
server_files/<username>/      # Files uploaded by each user
server_files/chat_history.txt # Chat payload log
```

Runtime files, local test artifacts, and PDFs are excluded from version control.

## Current limitations

This is an educational prototype intended for a local or trusted-network demonstration.

- Accounts, passwords, login state, and offline queues are stored in memory and disappear when the server restarts. Uploaded files and the chat log remain on disk.
- Chat text uses a reversible character shift of `+3`, reversed by the receiving client. This is obfuscation, not secure encryption. Credentials and files travel without TLS, and passwords are stored as plain text in memory.
- The upload limit checks the size declared by the client; the server does not enforce the actual byte count or validate chunk indexes and sizes.
- Usernames and filenames are not sanitized, and accepting a file does not verify an outstanding share request. Do not expose this implementation to untrusted users.
- Shared state and writes to a socket are not protected by locks. Concurrent operations can race; download transmission also starts before the acceptance acknowledgement, which can cause missing initial chunks. Keep demo transfers sequential and verify received files.
- Downloads with the same filename overwrite local files. There is no resume support or checksum verification.
