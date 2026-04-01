import { getEncoding,getEncodingNameForModel } from "js-tiktoken"; 

const modelName = "gpt-4"; 
const encodingName = getEncodingNameForModel(modelName);//获取这个模型使用的编码器名称 cl100k_base
console.log(encodingName);

//用这个编码来计算下 token 数量：
const enc = getEncoding("cl100k_base");
console.log('apple', enc.encode("apple").length);
console.log('pineapple', enc.encode("pineapple").length);
console.log('苹果', enc.encode("苹果").length);
console.log('吃饭', enc.encode("吃饭").length);
console.log('一二三', enc.encode("一二三").length);