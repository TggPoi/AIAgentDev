import "dotenv/config";
import tencentcloud from"tencentcloud-sdk-nodejs";
import fs from"node:fs";

const SECRET_ID = process.env.SECRET_ID;
const SECRET_KEY = process.env.SECRET_KEY;

const AsrClient = tencentcloud.asr.v20190614.Client;
const AUDIO_FILE = './output.mp3';

const client = new AsrClient({
credential: {
    secretId: SECRET_ID,
    secretKey: SECRET_KEY,
  },
region: "ap-shanghai",
profile: {
    httpProfile: {
      reqMethod: "POST",
      reqTimeout: 30,
    },
  },
});

async function run() {
const audioBase64 = fs.readFileSync(AUDIO_FILE).toString("base64");

const params = {
    EngSerViceType: "16k_zh",
    SourceType: 1,
    Data: audioBase64,
    DataLen: Buffer.byteLength(audioBase64),
    VoiceFormat: "mp3",
  };

try {
    // 调用语音识别接口，获取识别结果
    const data = await client.SentenceRecognition(params);
    console.log("识别结果：", data.Result);
  } catch (err) {
    console.error("识别失败：", err);
  }
}

run();

/**
 * PS D:\AI_Agent_Project\tts-stt-test> node .\src\asr-test.mjs
识别结果： 下班路上，我还在为晚霞开心，突然电话响起，系统崩了，我的心一下揪紧，冲进办公室时几乎要绝望。可当大家一起排查重启，屏幕终于恢复正常。我长长松了口气，笑着说，还好我们没放弃。
 */