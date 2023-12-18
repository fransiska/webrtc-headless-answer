#!/usr/bin/env python3

import asyncio
import os
import platform
import sys
import threading
import time

from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer
from firebase_admin import credentials, firestore, initialize_app

MAX_CALL_TIME_SEC = 120

def str_to_candidate(c, sdpMid):
    cs = c.split(" ")
    return RTCIceCandidate(
        component = int(cs[1]),
        foundation = cs[0].split(":")[1],
        ip = cs[4],
        port = int(cs[5]),
        priority = int(cs[3]),
        protocol = cs[2].upper(),
        type = cs[7],
        sdpMid = sdpMid
    )

def read_offer(call_ref):
    call_snapshot = call_ref.get().to_dict()

    # Received SDP
    sdp = call_snapshot["offer"]["sdp"]

    candidate_ref = call_ref.collection("offerCandidates")
    candidate_docs = candidate_ref.get()
    candidates = []
    for doc in candidate_docs:
        snapshot = doc.to_dict()
        candidates.append(str_to_candidate(snapshot["candidate"], snapshot["sdpMid"]))
        print("candidate", doc.id)
    return sdp, candidates

def get_player(video_path=None):
    if video_path:
        return MediaPlayer(video_path)
    elif platform.system() == "Darwin":
        # Mac OS
        return MediaPlayer('default:none', format='avfoundation', options={
            'framerate': '30',
            'video_size': '640x480'
        })
    else:
        # Linux
        return MediaPlayer("/dev/video0")

async def answer(call_ref, video_path):
    player = get_player(video_path)
    track = player.video

    pc = RTCPeerConnection()
    pc.addTrack(track)

    sdp, candidates = read_offer(call_ref)

    await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
    await pc.setLocalDescription(await pc.createAnswer())
    for c in candidates:
        await pc.addIceCandidate(c)

    call_ref.update({"answer": {"sdp": pc.localDescription.sdp, "type": "answer"}})

    print("answered")

    # Create an Event for notifying main thread.
    update_event = threading.Event()

    def on_snapshot(col_snapshot, changes, read_time):
        """There is no way to define this elsewhere since document.on_snapshot doesn't allow passing args
        """
        for change in changes:
            if change.type.name == "MODIFIED":
                hangup = col_snapshot[0].get('hangup')
                if hangup:
                    update_event.set()

    # Watch the collection query
    event_watch = call_ref.on_snapshot(on_snapshot)

    update_event.wait(MAX_CALL_TIME_SEC)

def main(offer_id, video_path, firebase_credentials_path):
    cred = credentials.Certificate(firebase_credentials_path)
    app = initialize_app(cred)
    db = firestore.client()
    call_ref = db.collection("calls").document(offer_id)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(answer(call_ref, video_path))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: FIREBASE_CREDENTIALS=firebase-adminsdk.json python answer.py <caller_id> <video_path>")
        exit()

    offer_id = sys.argv[1]
    if len(sys.argv) > 2:
        video_path = sys.argv[2]
    else:
        video_path = None
    main(offer_id, video_path, os.environ.get("FIREBASE_CREDENTIALS", "firebase-adminsdk.json"))
