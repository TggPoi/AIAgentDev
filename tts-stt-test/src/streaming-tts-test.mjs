import "dotenv/config";
import WebSocket from "ws";
import crypto from "node:crypto";
import fs from "node:fs";

const SECRET_ID = process.env.SECRET_ID;
const SECRET_KEY = process.env.SECRET_KEY;
const APP_ID = process.env.APP_ID;

const VOICE_TYPE = 101001;
const OUTPUT_FILE = "output3.mp3";
const TEXT_INTERVAL_MS = 3000;// 模拟实时输入文本的场景，每隔 3s 发送一段文本
const TEXTS = [
"傍晚我还在为晚霞开心，",
"突然接到电话说系统崩了，",
"我心里一沉冲回办公室，",
"好在大家一起排查后终于恢复，",
"我长长松了口气。",
];

const sleep = (ms) =>new Promise((resolve) => setTimeout(resolve, ms));

function buildWsUrl() {
    const now = Math.floor(Date.now() / 1000);
    const sessionId = `session_${now}_${Math.random().toString(36).slice(2)}`;

    const params = {
        Action: "TextToStreamAudioWSv2",
        AppId: parseInt(APP_ID),
        Codec: "mp3",
        Expired: now + 3600,
        SampleRate: 16000,
        SecretId: SECRET_ID,
        SessionId: sessionId,
        Speed: 0,
        Timestamp: now,
        VoiceType: VOICE_TYPE,
        Volume: 5,
      };

    const sortedKeys = Object.keys(params).sort();
    const signStr = sortedKeys.map((k) =>`${k}=${params[k]}`).join("&");
    const rawStr = `GETtts.cloud.tencent.com/stream_wsv2?${signStr}`;
    const signature = crypto
        .createHmac("sha1", SECRET_KEY)
        .update(rawStr)
        .digest("base64");
    const searchParams = new URLSearchParams({
        ...params,
        Signature: signature,
      });

    return {
        sessionId,
        url: `wss://tts.cloud.tencent.com/stream_wsv2?${searchParams.toString()}`,
      };
}

// 模拟实时输入文本的场景，每隔 3s 发送一段文本，最后发送 ACTION_COMPLETE 表示文本输入结束
async function sendTexts(ws, sessionId) {

    // 每隔 3s 发送一段文本，模拟实时输入的场景
    for (let i = 0; i < TEXTS.length; i++) {

        ws.send(JSON.stringify({ session_id: sessionId, message_id: `msg_${i}`, action: "ACTION_SYNTHESIS", data: TEXTS[i] }));

        console.log(`[文本] 已发送: ${TEXTS[i]}`);

        if (i < TEXTS.length - 1) await sleep(TEXT_INTERVAL_MS);
      }
      ws.send(JSON.stringify({ session_id: sessionId, action: "ACTION_COMPLETE" }));
      console.log("[文本] 已发送 ACTION_COMPLETE");
}

/**
 * 每 3s 发送一次消息然后用 fs.createWriteStream 异步写入文件
 * 因为文本是流式返回的，所以语音一般也要流式生成，用 streaming tts 的接口。
 */
function streamTTS() {
    if (!SECRET_ID || !SECRET_KEY || !APP_ID) {
        thrownewError("请先在 .env 配置 SECRET_ID、SECRET_KEY、APP_ID");
      }

    const { url, sessionId } = buildWsUrl();

    const ws = new WebSocket(url);

    const writeStream = fs.createWriteStream(OUTPUT_FILE, { flags: "w" });

    let totalBytes = 0;
    let closed = false;
    let sent = false;

    const closeAll = () => {
        if (closed) return;
        closed = true;
        writeStream.end(() => {
          console.log(`[保存] 音频已保存至 ${OUTPUT_FILE}，共 ${totalBytes} 字节`);
        });
        if (ws.readyState < WebSocket.CLOSING) ws.close();
      };

      ws.on("open", () => {
        console.log("[连接] WebSocket 已建立，等待服务端就绪...");
      });

      ws.on("message", async (data, isBinary) => {
        // 如果是二进制数据，直接写入文件
        if (isBinary) {
          writeStream.write(data);
          totalBytes += data.length;
          return;
        }

        try {
          const msg = JSON.parse(data.toString());
          console.log("[消息]", JSON.stringify(msg));

          if (msg.ready === 1 && !sent) {
            sent = true;
            await sendTexts(ws, sessionId);
          }

          if (msg.code && msg.code !== 0) {
            console.error(`[错误] code=${msg.code}, message=${msg.message}`);
            closeAll();
          } else if (msg.final === 1) {
            console.log("[完成] 合成结束。");
            closeAll();
          }
        } catch (e) {
          console.error("[解析错误]", e.message);
        }
      });

      ws.on("error", (err) => {
        console.error("[WebSocket 错误]", err.message);
        closeAll();
      });

      ws.on("close", (code, reason) => {
        console.log(`[断开] 连接已关闭，code=${code}, reason=${reason}`);
        closeAll();
      });
}

streamTTS();

/** 查看output3.mp3时，可以看到文本是分段返回的，音频也是分段返回的，最后合成完整的 mp3 文件，音频时长逐渐增加
 * 
 * PS D:\AI_Agent_Project\tts-stt-test> node .\src\streaming-tts-test.mjs
[连接] WebSocket 已建立，等待服务端就绪...
[消息] {"code":0,"message":"success","session_id":"session_1777445867_ifuy69v3osp","request_id":"c84b16d9-4111-4739-8f8f-1ac949e1d10e","message_id":"858924f3-4736-4224-8192-8c3a23419a3f","final":0,"ready":0,"heartbeat":0,"reset":0,"result":{"subtitles":null}}
[消息] {"code":0,"message":"success","session_id":"session_1777445867_ifuy69v3osp","request_id":"c84b16d9-4111-4739-8f8f-1ac949e1d10e","message_id":"b07e5eff-b472-489c-abf9-3c9795f169f6","final":0,"ready":1,"heartbeat":0,"reset":0,"result":{"subtitles":null}}
[文本] 已发送: 傍晚我还在为晚霞开心，
[文本] 已发送: 突然接到电话说系统崩了，
[文本] 已发送: 我心里一沉冲回办公室，
[文本] 已发送: 好在大家一起排查后终于恢复，
[消息] {"code":0,"message":"success","session_id":"session_1777445867_ifuy69v3osp","request_id":"c84b16d9-4111-4739-8f8f-1ac949e1d10e","message_id":"ca7c5f36-933d-41e2-b4f5-c3dcb3fab5a3","final":0,"ready":0,"heartbeat":1,"reset":0,"result":{"subtitles":null}}
[文本] 已发送: 我长长松了口气。
[文本] 已发送 ACTION_COMPLETE
[消息] {"code":0,"message":"success","session_id":"session_1777445867_ifuy69v3osp","request_id":"c84b16d9-4111-4739-8f8f-1ac949e1d10e","message_id":"dab8cdb7-9518-4d1d-b159-670874d6a196","final":1,"ready":0,"heartbeat":0,"reset":0,"result":{"subtitles":null}}
[完成] 合成结束。
[保存] 音频已保存至 output3.mp3，共 50688 字节
[断开] 连接已关闭，code=1005, reason=
 */