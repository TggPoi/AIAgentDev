import { Controller, Get, Query, Sse } from '@nestjs/common';
import { from, map, Observable } from 'rxjs';
import { AiService } from './ai.service';

@Controller('ai')
export class AiController {
constructor(private readonly aiService: AiService) {}

  @Get('chat')
async chat(@Query('query') query: string) {
    const answer = await this.aiService.runChain(query);
    return { answer };
  }

/**
 * 
 * 声明接口是 sse 的，然后创建一个 Observable，从 service 的返回流里读取内容，用 map 转成有 data 属性的对象这个是 rxjs 的写法，
 * Nest 用 rxjs 来处理异步流。其实和 LCEL 的声明式写法思路一样，就是声明对这个流做什么处理
 * 
 */
  @Sse('chat/stream')
  chatStream(@Query('query') query: string): Observable<{ data: string }> {
    //直接把streamChain返回的 AsyncGenerator 转成 Observable 流，然后用 map 操作符把每个 chunk 转成 { data: chunk } 的形式，
    // 这样前端就能以 sse 的方式接收流式数据了，因此streamChain中不需要写return了，直接yield每个chunk就行，yield的值会被 from 转成 Observable 流的每个数据项
    return from(this.aiService.streamChain(query)).pipe(
      map((chunk) => ({ data: chunk }))
    );
  }
}

//http://localhost:3000/ai/chat?query=蛋羹的做法
/**
 * {
  "answer": "蛋羹（又称蒸水蛋、鸡蛋羹）是一道口感滑嫩、营养易消化的传统家常菜，关键在于“水蛋比例”“过滤去泡”和“火候控制”。以下是经典家庭版做法（2人份）：\n\n✅ 【基础材料】  \n- 鸡蛋：3个（约150g蛋液）  \n- 温水（或高汤）：约300ml（蛋液:水 = 1:1.5，即1份蛋液配1.5份温水，这是嫩滑的关键）  \n- 盐：1/4小勺（约1.5g，可选加少许白胡椒粉提鲜）  \n- 香油/葱花/虾仁/肉末等：按喜好添加（可选）\n\n⚠️ 注意：务必用**温水（约40℃）或放凉的高汤**，不用冷水（易起蜂窝）也不用热水（会烫成蛋花）。\n\n✅ 【详细步骤】  \n1️⃣ **打蛋**：鸡蛋打入碗中，加盐，用筷子或打蛋器**轻柔画圈搅打**（避免大力搅打出过多气泡），至蛋液均匀、表面稍有泡沫即可，**不要过度打发**。\n\n2️⃣ **兑水**：将温水（或清鸡汤）缓缓倒入蛋液中，边倒边轻轻搅拌均匀。  \n✅ 小贴士：可用厨房秤称量更精准（如蛋液150g → 加温水225g）。\n\n3️⃣ **过滤去泡**（关键！）：将蛋液过筛2次（用细网筛或纱布），滤掉气泡和未散开的蛋筋，使质地更细腻。静置5分钟，让残留气泡浮出。\n\n4️⃣ **盖盖/覆膜**：  \n→ 倒入抹了薄油的蒸碗/深盘中（防粘）；  \n→ **盖上耐热盘盖、保鲜膜（扎几个小孔）或扣一个盘子**——防止水蒸气滴入造成蜂窝、表面不平。\n\n5️⃣ **蒸制**：  \n- 水烧开后，放入蛋液碗，**转中火（保持锅内水微沸，非大火猛蒸）**；  \n- 蒸约10–12分钟（视容器深浅而定，浅碗约10分钟，深碗12–15分钟）；  \n- 判断熟度：轻晃碗，蛋羹整体微微颤动如豆腐脑状，中心无液体晃动即熟。\n\n6️⃣ **出锅 & 点缀**：  \n- 关火后焖2分钟再揭盖（防塌陷）；  \n- 淋少许香油、生抽（可选），撒葱花、熟虾仁、蟹肉或肉末等；  \n- 喜欢鲜味可滴几滴芝麻油或浇一勺热高汤。\n\n🌟 【成功秘诀总结】  \n✔️ 比例准：蛋:水=1:1.5（喜欢更嫩可1:1.8，但需缩短蒸时）  \n✔️ 温水兑、不过热  \n✔️ 过滤+静置去泡  \n✔️ 盖盖防滴水  \n✔️ 中火慢蒸，忌大火沸腾  \n✔️ 蒸好焖2分钟再开盖  \n\n💡 变式推荐：  \n- 虾仁蒸蛋：蛋液中加入焯水虾仁，蒸前铺在表面；  \n- 肉末蒸蛋：肉末炒香后铺于凝固的蛋羹表面，再蒸2分钟；  \n- 日式茶碗蒸：加香菇、银杏、鸡肉丁，用日式出汁代替清水，更清雅。\n\n试试看，一次成功滑如镜、嫩似豆腐的完美蛋羹就来啦！🥚✨  \n需要视频要点提示或低脂/宝宝版（无盐少油）做法，也欢迎告诉我～"
}
 */


