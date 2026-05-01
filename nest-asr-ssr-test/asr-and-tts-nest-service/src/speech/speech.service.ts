import { Inject, Injectable } from '@nestjs/common';
import type * as tencentcloud from 'tencentcloud-sdk-nodejs';

type UploadedAudio = {
buffer: Buffer;
  originalname: string;
  mimetype: string;
  size: number;
};

type AsrClient = InstanceType<typeof tencentcloud.asr.v20190614.Client>;

@Injectable()
export class SpeechService {

constructor(@Inject('ASR_CLIENT') private readonly asrClient: AsrClient) {}

// 使用腾讯云语音识别服务对上传的音频文件进行识别，首先将音频文件转换为 Base64 编码格式，然后调用 ASR 客户端的 SentenceRecognition 方法发送识别请求，并返回识别结果中的文本内容，如果识别结果中没有文本则返回空字符串
async recognizeBySentence(file: UploadedAudio): Promise<string> {
    const audioBase64 = file.buffer.toString('base64');

    const result = await this.asrClient.SentenceRecognition({
      EngSerViceType: '16k_zh',
      SourceType: 1,
      Data: audioBase64,
      DataLen: file.buffer.length,
      VoiceFormat: 'ogg-opus',
    });

    return result.Result ?? '';
  }
}