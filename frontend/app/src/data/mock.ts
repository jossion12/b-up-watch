import type { Uploader, Video, TopicCluster } from '@/types'

export const uploaders: Uploader[] = [
  { id: 'u1', name: '林亦LYi', fans: '128.6万', category: 'AI·编程', color: '#FB7299', description: 'AI应用与开源项目实战', unread: 2, lastActive: '3小时前' },
  { id: 'u2', name: '量子位QbitAI', fans: '96.2万', category: 'AI·资讯', color: '#7C5CFF', description: '前沿AI资讯速递', unread: 2, lastActive: '5小时前' },
  { id: 'u3', name: '极客湾Geekerwan', fans: '412.8万', category: '数码·评测', color: '#00A1D6', description: '芯片与硬件深度评测', unread: 1, lastActive: '昨天' },
  { id: 'u4', name: '影视飓风', fans: '986.5万', category: '影像·科技', color: '#FF8A3D', description: '影像技术与器材测评', unread: 1, lastActive: '昨天' },
  { id: 'u5', name: '小Lin说', fans: '385.2万', category: '财经·商业', color: '#23C39E', description: '财经知识通俗解读', unread: 1, lastActive: '昨天' },
  { id: 'u6', name: '硬核的半佛仙人', fans: '763.4万', category: '商业·财经', color: '#F5A623', description: '商业逻辑硬核拆解', unread: 0, lastActive: '2天前' },
  { id: 'u7', name: '李永乐老师', fans: '612.7万', category: '科普·教育', color: '#4A90D9', description: '数理知识科普', unread: 0, lastActive: '2天前' },
  { id: 'u8', name: '罗翔说刑法', fans: '2480.3万', category: '法律·人文', color: '#8B5CF6', description: '刑法案例与法理', unread: 1, lastActive: '6小时前' },
  { id: 'u9', name: '老师好我叫何同学', fans: '1089.4万', category: '科技·数码', color: '#FF5C7A', description: '科技创意项目', unread: 0, lastActive: '2天前' },
  { id: 'u10', name: '无穷小亮的科普日常', fans: '1024.6万', category: '科普·自然', color: '#54B435', description: '网络热门生物鉴定', unread: 0, lastActive: '4天前' },
  { id: 'u11', name: '科技美学', fans: '388.9万', category: '数码·评测', color: '#00B8A9', description: '数码产品横评', unread: 0, lastActive: '2天前' },
  { id: 'u12', name: '分析师Boden', fans: '45.3万', category: '财经·投资', color: '#D96C4A', description: '二级市场与订单流分析', unread: 1, lastActive: '昨天' },
]

export const videos: Video[] = [
  {
    id: 'v1', bvid: 'BV1xK4y1A7Cd', upId: 'u1',
    title: '我花72小时复刻了开源版Manus，Agent真的能干活了吗',
    duration: '32:14', dateGroup: '今天', time: '10:32', publishedAt: '2026-07-19T10:32:00',
    views: '86.5万', danmaku: '1.2万', likes: '9.8万',
    tags: ['AI Agent', '开源', '实测'], status: 'summarized',
    gradient: 'from-pink-400 to-rose-500',
    summary: {
      brief: 'UP主用72小时基于开源框架复刻了一个类Manus的通用Agent，实测了网页浏览、代码编写、报告生成三类任务，成功率约70%，认为Agent已到「可用」临界点但离「好用」尚远。',
      points: [
        '基于开源框架搭建多Agent系统：规划层负责任务拆解，执行层调用浏览器与代码沙箱',
        '实测30个任务，成功率约70%；失败集中在长链路任务的上下文丢失',
        'Token成本是最大隐形成本，单个复杂任务平均消耗约12元',
        '与Manus的差距主要在工程细节：重试机制、工具描述质量和记忆压缩',
      ],
      stance: {
        label: '谨慎乐观',
        sentiment: 'mixed',
        detail: '认可Agent已跨过「能用」门槛，但强调当前营销热度远高于实际能力，普通用户现阶段更适合垂直场景Agent而非通用Agent',
      },
      topics: ['AI Agent', '多Agent框架', 'Manus', 'Token成本'],
      quote: 'Agent不是不能干活，是你得像带实习生一样带它——交代清楚、随时检查、做好返工的准备。',
    },
    subtitles: [
      { time: '00:00:12', text: '上个月Manus邀请码被炒到五万块，我就在想，这东西到底能不能自己做一个' },
      { time: '00:02:45', text: '整体架构其实不复杂，一个规划Agent，配三个执行Agent，工具层接浏览器和代码沙箱' },
      { time: '00:11:20', text: '30个任务跑下来，成功了21个，失败的9个里有6个是上下文断了' },
      { time: '00:23:08', text: '算笔账，平均一个复杂任务烧掉大概12块钱的token，这个成本很多人没概念' },
    ],
  },
  {
    id: 'v2', bvid: 'BV1mT4y1B7Ef', upId: 'u2',
    title: 'GPT-5.2发布：推理成本暴降80%，但benchmarks有猫腻？',
    duration: '08:42', dateGroup: '今天', time: '08:15', publishedAt: '2026-07-19T08:15:00',
    views: '45.2万', danmaku: '6800', likes: '3.2万',
    tags: ['大模型', 'OpenAI'], status: 'downloaded',
    gradient: 'from-violet-400 to-purple-600',
    summary: {
      brief: 'OpenAI发布GPT-5.2，推理成本下降80%，多项基准测试刷新纪录，但视频质疑部分测试集存在数据污染，建议关注第三方独立评测结果。',
      points: [
        'API价格降至上代的1/5，输入每百万token 0.8美元',
        '数学与代码基准提升显著，但部分测试集疑似泄露进训练数据',
        '多家机构正在复测，初步结果比官方数据低5-8个百分点',
      ],
      stance: {
        label: '中立偏质疑',
        sentiment: 'neutral',
        detail: '肯定降价对开发者的实际利好，但对官方跑分持保留态度，呼吁等待独立评测',
      },
      topics: ['GPT-5.2', '大模型降价', '基准测试'],
      quote: '跑分是广告，价格是诚意。',
    },
    subtitles: [
      { time: '00:00:30', text: '今天凌晨OpenAI悄悄发了GPT-5.2，最狠的不是分数，是价格' },
      { time: '00:03:15', text: '但有研究员发现，官方用的几个测试集，和训练语料重合度有点高' },
    ],
  },
  {
    id: 'v3', bvid: 'BV1nR4y1C7Gh', upId: 'u8',
    title: 'AI换脸拟声诈骗横行，法律到底管不管得住',
    duration: '14:26', dateGroup: '今天', time: '07:50', publishedAt: '2026-07-19T07:50:00',
    views: '158.3万', danmaku: '2.1万', likes: '12.6万',
    tags: ['法律', 'AI', '社会'], status: 'new',
    gradient: 'from-indigo-400 to-blue-600',
    summary: {
      brief: '从近期多起AI换脸拟声诈骗案切入，讲解现行刑法中诈骗罪、侵犯公民个人信息罪的适用边界，指出技术中立原则下平台责任的认定难点。',
      points: [
        'AI换脸拟声本身不违法，关键在于使用目的与是否获利',
        '现行法律对「深度合成」已有标识义务要求，但执行层面存在取证难',
        '平台是否尽到审核义务，是民事追责的核心争议点',
      ],
      stance: {
        label: '呼吁立法细化',
        sentiment: 'neutral',
        detail: '认为现行法律框架基本够用，但司法解释需要跟上技术迭代速度',
      },
      topics: ['AI治理', '深度合成', '刑法'],
      quote: '技术跑在立法前面是常态，但司法不能一直原地踏步。',
    },
    subtitles: [
      { time: '00:01:10', text: '张三最近收到一段视频，里面是他儿子，哭着说被绑架了' },
      { time: '00:06:33', text: '技术本身是中立的，菜刀能切菜也能伤人，问题从来不在刀' },
    ],
  },
  {
    id: 'v4', bvid: 'BV1pS4y1D7Jk', upId: 'u3',
    title: '麒麟9030深度实测：这回真的追上了吗',
    duration: '28:50', dateGroup: '昨天', time: '21:06', publishedAt: '2026-07-18T21:06:00',
    views: '210.6万', danmaku: '3.4万', likes: '18.9万',
    tags: ['芯片', '华为', '实测'], status: 'summarized',
    gradient: 'from-cyan-400 to-blue-500',
    summary: {
      brief: '对麒麟9030进行CPU/GPU/能效全维度实测，CPU多核性能接近骁龙8 Gen4，GPU仍有15%左右差距，但能效比大幅改善，日常体验已基本无感。',
      points: [
        'CPU多核跑分达到骁龙8 Gen4的95%，单核仍有约10%差距',
        'GPU峰值性能差15%，但中低频段能效反超，游戏实测帧率稳定',
        'NPU本地大模型推理速度翻倍，7B模型可流畅本地运行',
        '制程受限于国产产线，靠架构优化和封装补偿，功耗控制出乎意料',
      ],
      stance: {
        label: '谨慎乐观',
        sentiment: 'positive',
        detail: '承认绝对性能仍有差距，但强调从「不可用」到「日常无感」是质变，对国产供应链的长期意义大于单点性能',
      },
      topics: ['麒麟9030', '国产芯片', '手机SoC'],
      quote: '追平不是一夜之间发生的，是从「没法用」到「够用」再到「好用」一步步磨出来的。',
    },
    subtitles: [
      { time: '00:00:45', text: '这颗麒麟9030，可能是今年争议最大的一颗芯片，我们直接上数据' },
      { time: '00:09:12', text: 'GPU峰值确实还差一截，但你注意看中低频的能效曲线，这里反超了' },
      { time: '00:21:30', text: '7B参数的大模型现在能在这颗芯片上本地跑，速度还相当不错' },
    ],
  },
  {
    id: 'v5', bvid: 'BV1qU4y1E7Lm', upId: 'u5',
    title: 'A股冲上4000点，这轮行情的底层逻辑是什么',
    duration: '18:22', dateGroup: '昨天', time: '19:40', publishedAt: '2026-07-18T19:40:00',
    views: '95.8万', danmaku: '1.5万', likes: '6.4万',
    tags: ['A股', '投资', '宏观'], status: 'summarized',
    gradient: 'from-emerald-400 to-teal-600',
    summary: {
      brief: '拆解本轮行情的三大驱动：流动性宽松、AI产业叙事与居民存款搬家，认为指数层面仍有空间但结构分化严重，提示追高风险。',
      points: [
        '本轮行情核心驱动是流动性：降准降息后市场无风险利率持续走低',
        'AI产业链贡献了主要涨幅，TMT板块成交额占比已达历史高位',
        '居民存款通过ETF加速入市，7月股票型ETF净申购创单月纪录',
        '历史对比：当前估值分位约65%，未到泡沫区但已不是便宜货',
      ],
      stance: {
        label: '看多但提示风险',
        sentiment: 'mixed',
        detail: '认可趋势未破坏，但强调这是「强结构市」，追高AI概念股的风险收益比正在恶化',
      },
      topics: ['A股', '牛市', '流动性', 'AI板块'],
      quote: '牛市里最贵的四个字是「这次不一样」——每次都一样，也每次都不一样。',
    },
    subtitles: [
      { time: '00:01:20', text: '4000点了，我的后台全是同一个问题：现在还能不能上车' },
      { time: '00:08:45', text: '这轮钱从哪来？看一个数据就够了，7月股票ETF净申购量，历史第一' },
    ],
  },
  {
    id: 'v6', bvid: 'BV1rV4y1F7Np', upId: 'u4',
    title: '8K 120fps！我们把频道画质卷到了新高度',
    duration: '16:08', dateGroup: '昨天', time: '18:02', publishedAt: '2026-07-18T18:02:00',
    views: '132.4万', danmaku: '9800', likes: '10.2万',
    tags: ['影像', '8K', '科技'], status: 'new',
    gradient: 'from-orange-400 to-red-500',
    summary: {
      brief: '影视飓风宣布频道升级至8K 120fps制作流程，展示了新工作流程与存储方案，讨论了高规格制作对内容行业的意义。',
      points: [
        '全流程8K 120fps：拍摄、剪辑、调色、交付',
        '单条视频素材量达40TB，存储与算力成本翻倍',
        '认为画质升级是「供给侧改革」，观众体验阈值不可逆',
      ],
      stance: {
        label: '积极探索',
        sentiment: 'positive',
        detail: '承认投入产出比存疑，但认为技术探索本身就是内容竞争力',
      },
      topics: ['8K', '影像技术', '内容制作'],
      quote: '当你看过120帧的世界，就再也回不去了。',
    },
    subtitles: [
      { time: '00:00:20', text: '这条视频本身，就是用8K 120帧制作的第一条片子' },
    ],
  },
  {
    id: 'v7', bvid: 'BV1sW4y1G7Qr', upId: 'u12',
    title: '南向资金狂买800亿，港股正在发生什么',
    duration: '12:35', dateGroup: '昨天', time: '16:24', publishedAt: '2026-07-18T16:24:00',
    views: '22.1万', danmaku: '3200', likes: '1.8万',
    tags: ['港股', '资金流向'], status: 'downloaded',
    gradient: 'from-amber-400 to-orange-600',
    summary: {
      brief: '统计近一月南向资金净流入超800亿港元，主要流向高股息央国企与科技龙头，分析险资与公募的配置逻辑差异。',
      points: [
        '南向资金连续20日净流入，险资偏好高股息，公募加仓科技',
        '港股通成交额占港股总成交比例升至历史新高',
        '提示汇率对冲成本上升对后续流入速度的抑制',
      ],
      stance: {
        label: '看多',
        sentiment: 'positive',
        detail: '认为南向定价权提升是中长期趋势，港股估值修复尚未结束',
      },
      topics: ['南向资金', '港股', '高股息'],
      quote: '定价权的转移，从来都是悄无声息的。',
    },
    subtitles: [
      { time: '00:02:00', text: '一个月800亿，这个速度放在港股通开通以来的任何时期都是排前列的' },
    ],
  },
  {
    id: 'v8', bvid: 'BV1tX4y1H7St', upId: 'u6',
    title: '车企为什么排着队给华为送钱',
    duration: '21:40', dateGroup: '7月17日', time: '20:15', publishedAt: '2026-07-17T20:15:00',
    views: '188.2万', danmaku: '2.8万', likes: '14.3万',
    tags: ['华为', '汽车', '商业'], status: 'summarized',
    gradient: 'from-yellow-400 to-amber-600',
    summary: {
      brief: '拆解华为与车企合作的三种模式（零部件供应、HI模式、智选车/鸿蒙智行），分析车企让渡「灵魂」背后的生存焦虑与利益算计。',
      points: [
        '三种合作模式递进：卖零件→卖方案→联合定义产品并共担渠道',
        '鸿蒙智行模式下华为拿走约10%销售额，但带来3-5倍销量提升',
        '车企的核心焦虑：智能化投入百亿级且大概率自研失败，不如花钱买确定性',
        '风险在于品牌话语权稀释，「含华量」成为双刃剑',
      ],
      stance: {
        label: '理性分析',
        sentiment: 'neutral',
        detail: '不站队任何一方，认为这是一场各取所需的交易，但警告过度依赖单一供应商的长期风险',
      },
      topics: ['华为', '鸿蒙智行', '智能车', '商业模式'],
      quote: '当所有人都在骂你卖灵魂的时候，说明你手里的灵魂还挺值钱。',
    },
    subtitles: [
      { time: '00:01:05', text: '任正非说华为不造车，但现在的车企，排队给华为交钱，为什么' },
      { time: '00:12:40', text: '智选模式下华为抽成大概销售额的10%，听起来狠，但人家能给你翻三倍的量' },
    ],
  },
  {
    id: 'v9', bvid: 'BV1uY4y1I7Uv', upId: 'u7',
    title: '用数学讲明白：大模型的注意力机制到底是什么',
    duration: '24:10', dateGroup: '7月17日', time: '17:30', publishedAt: '2026-07-17T17:30:00',
    views: '76.3万', danmaku: '1.1万', likes: '5.9万',
    tags: ['AI', '数学', '科普'], status: 'new',
    gradient: 'from-sky-400 to-cyan-600',
    summary: {
      brief: '从向量点积与 softmax 出发，推导自注意力机制的数学原理，解释QKV矩阵的直觉含义，适合有线性代数基础的观众。',
      points: [
        '注意力的本质是加权平均，权重来自查询与键的相似度',
        '缩放点积避免梯度消失，是Transformer稳定训练的关键细节',
        '多头注意力相当于在不同子空间并行捕捉多种依赖关系',
      ],
      stance: {
        label: '教学中性',
        sentiment: 'neutral',
        detail: '纯知识讲解，无商业立场',
      },
      topics: ['Transformer', '注意力机制', '数学'],
      quote: '所谓智能，在数学上不过是一次恰到好处的加权平均。',
    },
    subtitles: [
      { time: '00:03:20', text: 'Query、Key、Value，这三个矩阵听起来玄乎，其实就是查字典' },
    ],
  },
  {
    id: 'v10', bvid: 'BV1vZ4y1J7Wx', upId: 'u9',
    title: '我做了一个会自己写代码的桌面机器人',
    duration: '12:58', dateGroup: '7月17日', time: '15:00', publishedAt: '2026-07-17T15:00:00',
    views: '320.5万', danmaku: '4.6万', likes: '28.7万',
    tags: ['AI', '机器人', 'DIY'], status: 'summarized',
    gradient: 'from-rose-400 to-pink-600',
    summary: {
      brief: '何同学自制桌面机器人，接入本地大模型与Agent框架，能通过语音指令操控电脑完成编程、查资料等任务，重点展示了三次失败的迭代过程。',
      points: [
        '硬件成本控制在2000元内：3D打印外壳+舵机+旧手机改造',
        '软件侧用Agent框架编排工具调用，语音→任务拆解→执行→反馈',
        '诚实展示失败：第一版成功率不到20%，调试两个月才到可用水平',
        '强调「具身智能」的交互温度，屏幕表情比语音更能建立陪伴感',
      ],
      stance: {
        label: '乐观',
        sentiment: 'positive',
        detail: '认为个人AI硬件将在两年内爆发，DIY社区会成为创新源头',
      },
      topics: ['AI Agent', '具身智能', 'DIY硬件'],
      quote: '它写出来的代码很烂，但它写代码的样子，真的很迷人。',
    },
    subtitles: [
      { time: '00:00:15', text: '过去两个月，我大部分时间都花在跟这个小家伙较劲上' },
      { time: '00:08:30', text: '成功率从20%到85%，我没有换模型，我只是学会了怎么跟它说话' },
    ],
  },
  {
    id: 'v11', bvid: 'BV1wA4y1K7Yz', upId: 'u11',
    title: '2026年中旗舰横评：谁才是真正的水桶机',
    duration: '35:20', dateGroup: '7月17日', time: '12:10', publishedAt: '2026-07-17T12:10:00',
    views: '68.9万', danmaku: '8900', likes: '4.2万',
    tags: ['手机', '横评'], status: 'new',
    gradient: 'from-teal-400 to-green-600',
    summary: {
      brief: '对8款年中旗舰进行屏幕、性能、影像、续航四大维度横评，给出不同预算下的购买建议。',
      points: [
        '性能差距普遍拉不开，系统体验成为新分水岭',
        '影像方面大底主摄同质化，长焦微距成为差异化卖点',
      ],
      stance: {
        label: '中立测评',
        sentiment: 'neutral',
        detail: '数据导向，无品牌偏好',
      },
      topics: ['旗舰手机', '横评'],
      quote: '参数表赢不了体验，体验赢不了价格。',
    },
    subtitles: [
      { time: '00:01:00', text: '八台机器，三十项测试，先说结论：今年没有完美的手机' },
    ],
  },
  {
    id: 'v12', bvid: 'BV1xB4y1L7Ab', upId: 'u2',
    title: 'Claude Code实战：一个人就是一支团队？',
    duration: '10:15', dateGroup: '7月16日', time: '22:40', publishedAt: '2026-07-16T22:40:00',
    views: '52.7万', danmaku: '7600', likes: '4.8万',
    tags: ['AI', '编程', 'Agent'], status: 'summarized',
    gradient: 'from-purple-400 to-violet-600',
    summary: {
      brief: '实测用Claude Code独立开发一个完整SaaS应用（含前后端与部署），耗时3天，代码采纳率约80%，认为「vibe coding」正在改变独立开发者的工作方式。',
      points: [
        '3天完成传统团队2周的工作量，但调试时间占比达40%',
        'AI生成代码的最大问题不是错误，是「看似合理的设计妥协」',
        '建议建立自动化验证harness：测试+lint+类型检查拦住低级错误',
        '成本核算：全程API费用约300元，远低于人力成本',
      ],
      stance: {
        label: '乐观但务实',
        sentiment: 'positive',
        detail: '认可效率提升是数量级的，但强调使用者的工程能力决定上限——AI放大的是判断力，不是替代判断力',
      },
      topics: ['Claude Code', 'vibe coding', '独立开发'],
      quote: 'AI没有让我变成十倍工程师，它让我敢接以前不敢接的活。',
    },
    subtitles: [
      { time: '00:01:40', text: '一个完整的SaaS，从数据库设计到部署上线，我一个人，三天' },
      { time: '00:06:20', text: '它写的代码能跑，但你仔细看架构，全是隐形的妥协' },
    ],
  },
  {
    id: 'v13', bvid: 'BV1yC4y1M7Cd', upId: 'u5',
    title: '黄金又双叒新高了，普通人现在还能上车吗',
    duration: '15:44', dateGroup: '7月16日', time: '20:05', publishedAt: '2026-07-16T20:05:00',
    views: '88.6万', danmaku: '1.3万', likes: '5.6万',
    tags: ['黄金', '投资'], status: 'downloaded',
    gradient: 'from-amber-300 to-yellow-500',
    summary: {
      brief: '分析金价新高的三大推手：央行购金、地缘风险与美元信用弱化，建议普通投资者以定投方式配置5-10%仓位，避免一次性追高。',
      points: [
        '全球央行连续9个季度净购金，去美元化是长逻辑',
        '黄金与美债实际利率的传统负相关关系近年失效',
        '普通投资者建议定投黄金ETF，仓位控制在资产的5-10%',
      ],
      stance: {
        label: '长期看多短期谨慎',
        sentiment: 'mixed',
        detail: '认可黄金的配置价值，但当前价位追高的胜率不高',
      },
      topics: ['黄金', '资产配置', '央行购金'],
      quote: '黄金不产生任何现金流，它唯一的价值是全人类共同的焦虑。',
    },
    subtitles: [
      { time: '00:02:30', text: '各国央行买金的速度，是过去五十年里最快的' },
    ],
  },
  {
    id: 'v14', bvid: 'BV1zD4y1N7Ef', upId: 'u1',
    title: 'RAG已死？聊聊我眼中的下一代检索范式',
    duration: '26:30', dateGroup: '7月16日', time: '18:22', publishedAt: '2026-07-16T18:22:00',
    views: '41.2万', danmaku: '5200', likes: '3.1万',
    tags: ['RAG', 'AI', '技术'], status: 'new',
    gradient: 'from-fuchsia-400 to-pink-600',
    summary: {
      brief: '回应「RAG已死」的行业争论，梳理从Naive RAG到Agentic RAG的演进路径，认为检索不会消失，但会与记忆系统深度融合。',
      points: [
        '「RAG已死」的论调源于长上下文模型的崛起，但成本与延迟决定了检索不可替代',
        'Agentic RAG把检索变成Agent的主动行为而非固定管道',
        '未来方向：检索、记忆、工具的边界将模糊，统一为「上下文工程」',
      ],
      stance: {
        label: '反对标题党',
        sentiment: 'neutral',
        detail: '认为「XX已死」式论断缺乏工程视角，技术范式是演进而非替代',
      },
      topics: ['RAG', 'Agentic RAG', '上下文工程'],
      quote: '每次有人说某个技术已死，它往往正在规模化落地的路上。',
    },
    subtitles: [
      { time: '00:01:15', text: '上周又有一篇爆文说RAG已死，我的评论区就炸了' },
    ],
  },
  {
    id: 'v15', bvid: 'BV1aE4y1P7Gh', upId: 'u10',
    title: '鉴定网络热门生物视频 68',
    duration: '18:20', dateGroup: '7月15日', time: '19:30', publishedAt: '2026-07-15T19:30:00',
    views: '245.8万', danmaku: '3.2万', likes: '16.4万',
    tags: ['自然', '科普'], status: 'new',
    gradient: 'from-green-400 to-emerald-600',
    summary: {
      brief: '鉴定本期热门生物视频，包括罕见的深海栉水母与「会走路的鱼」，辟谣两个AI生成的虚假动物视频。',
      points: [
        '深海栉水母的发光是机械感应荧光蛋白，非生物电',
        '本期首次出现AI生成动物视频以假乱真，给出三个鉴别要点',
      ],
      stance: {
        label: '科普中性',
        sentiment: 'neutral',
        detail: '对AI伪造内容的泛滥表达担忧',
      },
      topics: ['生物鉴定', 'AI伪造'],
      quote: '以后鉴定热门生物，得先鉴定它是不是AI生的。',
    },
    subtitles: [
      { time: '00:05:40', text: '这个视频播放量两千万，但我告诉大家，这动物不存在，是AI做的' },
    ],
  },
  {
    id: 'v16', bvid: 'BV1bF4y1Q7Jk', upId: 'u12',
    title: '从订单流看本轮反弹：主力到底在买什么',
    duration: '16:42', dateGroup: '7月15日', time: '16:45', publishedAt: '2026-07-15T16:45:00',
    views: '18.5万', danmaku: '2100', likes: '1.2万',
    tags: ['A股', '订单流'], status: 'new',
    gradient: 'from-red-400 to-rose-600',
    summary: {
      brief: '用订单流数据复盘本轮反弹，大单净流入集中在AI算力与创新药板块，散户参与度仍低，属于机构主导行情。',
      points: [
        '特大单净流入前五：算力、创新药、券商、机器人、军工',
        '散户资金（小单）仍在净流出，市场情绪未到亢奋期',
      ],
      stance: {
        label: '看多',
        sentiment: 'positive',
        detail: '机构主导+散户未入场，从历史规律看行情处于中段而非尾声',
      },
      topics: ['订单流', '主力资金', 'A股'],
      quote: '数据不会陪你情绪化，大单的方向就是钱的态度。',
    },
    subtitles: [
      { time: '00:03:10', text: '把过去二十天的大单流向画成图，主线清晰得可怕' },
    ],
  },
  {
    id: 'v17', bvid: 'BV1cG4y1R7Lm', upId: 'u3',
    title: 'RTX 5090D v2评测：老黄的刀法还是这么精准',
    duration: '22:15', dateGroup: '7月15日', time: '14:00', publishedAt: '2026-07-15T14:00:00',
    views: '156.3万', danmaku: '2.2万', likes: '9.8万',
    tags: ['显卡', '评测'], status: 'new',
    gradient: 'from-slate-400 to-gray-600',
    summary: {
      brief: 'RTX 5090D v2在AI算力上进一步阉割以符合出口管制，游戏性能保留95%，分析其对游戏玩家与AI用户的不同影响。',
      points: [
        'AI算力砍至原版60%，但游戏性能仅损失5%',
        '对纯游戏玩家影响不大，本地AI用户建议关注替代方案',
      ],
      stance: {
        label: '中立',
        sentiment: 'neutral',
        detail: '客观呈现规格差异，购买建议分人群给出',
      },
      topics: ['RTX 5090D', '显卡', 'AI算力'],
      quote: '这张卡的存在本身，就是一本地缘政治教科书。',
    },
    subtitles: [
      { time: '00:02:20', text: '游戏性能砍了5%，AI算力砍了40%，老黄这刀，精准得让人心疼' },
    ],
  },
  {
    id: 'v18', bvid: 'BV1dH4y1S7Np', upId: 'u4',
    title: '我们花了一个月，只为拍好这一条广告',
    duration: '20:05', dateGroup: '7月14日', time: '20:30', publishedAt: '2026-07-14T20:30:00',
    views: '98.4万', danmaku: '1.1万', likes: '7.3万',
    tags: ['幕后', '影像'], status: 'new',
    gradient: 'from-blue-400 to-indigo-600',
    summary: {
      brief: '记录一条汽车广告从创意到交付的全过程，展示商业片背后的工程化管理。',
      points: ['单条广告动用40人团队，拍摄12天', '商业化与内容调性的平衡是长期课题'],
      stance: { label: '分享', sentiment: 'neutral', detail: '幕后纪实' },
      topics: ['商业片', '幕后'],
      quote: '观众看到的是30秒，我们过的是30天。',
    },
    subtitles: [
      { time: '00:01:30', text: '这条片子客户给了一个月，我们真就用满了一个月' },
    ],
  },
  {
    id: 'v19', bvid: 'BV1eJ4y1T7Qr', upId: 'u2',
    title: 'Agent协议的战国时代：MCP、A2A 与 ANP 万字详解',
    duration: '18:45', dateGroup: '7月13日', time: '21:30', publishedAt: '2026-07-13T21:30:00',
    views: '38.6万', danmaku: '5600', likes: '2.9万',
    tags: ['AI Agent', 'MCP', '协议'], status: 'downloaded',
    gradient: 'from-violet-500 to-purple-700',
    summary: {
      brief: '系统对比三大Agent协议的设计哲学与生态现状，认为MCP凭先发优势暂时领先，但开放标准之争远未结束。',
      points: [
        'MCP解决模型与工具的连接，A2A解决Agent之间的协作，ANP主打去中心化身份',
        '生态采用度：MCP客户端数量是A2A的6倍，但大厂正在两边下注',
      ],
      stance: { label: '中立观察', sentiment: 'neutral', detail: '协议之争本质是生态入口之争，开发者应抽象适配层而非押注单一标准' },
      topics: ['MCP', 'A2A', 'Agent协议'],
      quote: '每个时代的基础设施之争，最后赢的都是生态，不是技术。',
    },
    subtitles: [
      { time: '00:01:20', text: '今年Agent领域最卷的不是模型，是协议' },
    ],
  },
  {
    id: 'v20', bvid: 'BV1fK4y1U7St', upId: 'u6',
    title: '外卖大战又起：百亿补贴烧不出护城河',
    duration: '19:26', dateGroup: '7月12日', time: '19:50', publishedAt: '2026-07-12T19:50:00',
    views: '142.3万', danmaku: '1.9万', likes: '9.6万',
    tags: ['商业', '外卖', '补贴'], status: 'new',
    gradient: 'from-amber-400 to-orange-600',
    subtitles: [
      { time: '00:00:50', text: '奶茶一块钱一杯的时候，你就该知道，又有人开始烧钱了' },
    ],
  },
  {
    id: 'v21', bvid: 'BV1gL4y1V7Uv', upId: 'u3',
    title: '2nm时代来了：A20 Pro 与天玑9600 前瞻分析',
    duration: '25:40', dateGroup: '7月11日', time: '20:00', publishedAt: '2026-07-11T20:00:00',
    views: '98.7万', danmaku: '1.4万', likes: '6.8万',
    tags: ['芯片', '2nm', '前瞻'], status: 'new',
    gradient: 'from-cyan-500 to-blue-700',
    subtitles: [
      { time: '00:02:10', text: '台积电2nm的良率，比我们预想的要好得多' },
    ],
  },
  {
    id: 'v22', bvid: 'BV1hM4y1W7Wx', upId: 'u5',
    title: '日元又崩了？一次讲懂套息交易的来龙去脉',
    duration: '16:15', dateGroup: '7月10日', time: '18:30', publishedAt: '2026-07-10T18:30:00',
    views: '67.4万', danmaku: '8900', likes: '4.1万',
    tags: ['日元', '宏观', '套息交易'], status: 'new',
    gradient: 'from-emerald-500 to-teal-700',
    subtitles: [
      { time: '00:01:40', text: '全球最便宜的钱在日本，这笔账全世界算了三十年' },
    ],
  },
  {
    id: 'v23', bvid: 'BV1iN4y1X7Yz', upId: 'u8',
    title: '网络暴力入刑：惩治与言论边界的平衡',
    duration: '13:52', dateGroup: '7月13日', time: '12:00', publishedAt: '2026-07-13T12:00:00',
    views: '203.8万', danmaku: '2.6万', likes: '15.2万',
    tags: ['法律', '网暴', '社会'], status: 'new',
    gradient: 'from-indigo-500 to-blue-700',
    subtitles: [
      { time: '00:01:05', text: '雪崩的时候，每一片雪花都觉得自己是无辜的' },
    ],
  },
]

// ============ 洞察页数据 ============

export const trendData = [
  { date: '7/13', 'AI Agent': 2, '华为·芯片': 1, 'A股·投资': 1, '影像·硬件': 2 },
  { date: '7/14', 'AI Agent': 3, '华为·芯片': 2, 'A股·投资': 1, '影像·硬件': 3 },
  { date: '7/15', 'AI Agent': 3, '华为·芯片': 3, 'A股·投资': 2, '影像·硬件': 1 },
  { date: '7/16', 'AI Agent': 5, '华为·芯片': 2, 'A股·投资': 3, '影像·硬件': 1 },
  { date: '7/17', 'AI Agent': 5, '华为·芯片': 4, 'A股·投资': 2, '影像·硬件': 2 },
  { date: '7/18', 'AI Agent': 6, '华为·芯片': 5, 'A股·投资': 4, '影像·硬件': 3 },
  { date: '7/19', 'AI Agent': 7, '华为·芯片': 4, 'A股·投资': 5, '影像·硬件': 2 },
]

export const hotWords = [
  { text: 'AI Agent', size: 'xl', heat: 98 },
  { text: '麒麟9030', size: 'lg', heat: 86 },
  { text: 'A股4000点', size: 'lg', heat: 82 },
  { text: '鸿蒙智行', size: 'md', heat: 74 },
  { text: '大模型降价', size: 'md', heat: 70 },
  { text: 'vibe coding', size: 'md', heat: 66 },
  { text: '南向资金', size: 'sm', heat: 58 },
  { text: '黄金新高', size: 'sm', heat: 52 },
  { text: '具身智能', size: 'sm', heat: 48 },
  { text: 'RAG', size: 'sm', heat: 44 },
  { text: '8K 120fps', size: 'xs', heat: 36 },
  { text: '订单流', size: 'xs', heat: 30 },
  { text: 'AI伪造', size: 'xs', heat: 26 },
]

export const topicClusters: TopicCluster[] = [
  {
    id: 't1',
    topic: 'AI Agent 是否迎来爆发期',
    heat: 98,
    videoCount: 5,
    opinions: [
      {
        upId: 'u9', sentiment: 'positive', stance: '乐观',
        opinion: '个人AI硬件两年内爆发，DIY社区会成为创新源头',
        videoTitle: '我做了一个会自己写代码的桌面机器人',
      },
      {
        upId: 'u1', sentiment: 'mixed', stance: '谨慎乐观',
        opinion: 'Agent已到「可用」临界点，但营销热度远超实际能力，通用Agent尚不成熟',
        videoTitle: '我花72小时复刻了开源版Manus',
      },
      {
        upId: 'u2', sentiment: 'positive', stance: '乐观务实',
        opinion: 'vibe coding效率提升是数量级的，但使用者的工程能力决定上限',
        videoTitle: 'Claude Code实战',
      },
      {
        upId: 'u1', sentiment: 'neutral', stance: '理性',
        opinion: '检索与Agent将融合为「上下文工程」，范式是演进而非替代',
        videoTitle: 'RAG已死？聊聊下一代检索范式',
      },
    ],
  },
  {
    id: 't2',
    topic: '华为生态的扩张逻辑',
    heat: 86,
    videoCount: 3,
    opinions: [
      {
        upId: 'u6', sentiment: 'neutral', stance: '理性分析',
        opinion: '车企买华为是花钱买确定性，各取所需，但依赖单一供应商有长期风险',
        videoTitle: '车企为什么排着队给华为送钱',
      },
      {
        upId: 'u3', sentiment: 'positive', stance: '谨慎乐观',
        opinion: '麒麟9030日常体验已无感，国产供应链的长期意义大于单点性能',
        videoTitle: '麒麟9030深度实测',
      },
    ],
  },
  {
    id: 't3',
    topic: 'A股行情能否持续',
    heat: 82,
    videoCount: 3,
    opinions: [
      {
        upId: 'u12', sentiment: 'positive', stance: '看多',
        opinion: '机构主导+散户未入场，行情处于中段而非尾声',
        videoTitle: '从订单流看本轮反弹',
      },
      {
        upId: 'u5', sentiment: 'mixed', stance: '谨慎看多',
        opinion: '流动性驱动未破坏，但结构分化严重，追高AI概念风险收益比恶化',
        videoTitle: 'A股冲上4000点的底层逻辑',
      },
      {
        upId: 'u12', sentiment: 'positive', stance: '看多',
        opinion: '南向定价权提升是中长期趋势，港股估值修复未结束',
        videoTitle: '南向资金狂买800亿',
      },
    ],
  },
  {
    id: 't4',
    topic: 'AI能力边界与社会治理',
    heat: 64,
    videoCount: 3,
    opinions: [
      {
        upId: 'u8', sentiment: 'neutral', stance: '呼吁立法',
        opinion: '现行刑法框架够用，但司法解释需跟上技术迭代',
        videoTitle: 'AI换脸拟声诈骗，法律管得住吗',
      },
      {
        upId: 'u10', sentiment: 'negative', stance: '担忧',
        opinion: 'AI伪造生物视频已以假乱真，科普内容面临信任危机',
        videoTitle: '鉴定网络热门生物视频 68',
      },
      {
        upId: 'u2', sentiment: 'neutral', stance: '质疑',
        opinion: '官方跑分需第三方复测验证， benchmark 污染是老问题',
        videoTitle: 'GPT-5.2发布',
      },
    ],
  },
]

