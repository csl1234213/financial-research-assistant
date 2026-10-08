import type { Language } from '../types/language';

export interface Translation {
  documentTitle: string;
  language: {
    label: string;
    english: string;
    chinese: string;
  };
  app: {
    restoringSession: string;
    nav: {
      newChat: string;
      chat: string;
      knowledge: string;
      retrieval: string;
      settings: string;
      logout: string;
    };
  };
  auth: {
    eyebrow: string;
    loginTitle: string;
    registerTitle: string;
    loginSubtitle: string;
    registerSubtitle: string;
    modeLabel: string;
    login: string;
    register: string;
    name: string;
    email: string;
    password: string;
    failed: string;
    creatingAccount: string;
    signingIn: string;
    createAccount: string;
    signIn: string;
  };
  header: {
    title: string;
    chatSubtitle: string;
    knowledgeSubtitle: string;
    retrievalSubtitle: string;
    documentSubtitle: string;
    settingsSubtitle: string;
    systemStatus: string;
    connected: string;
    offline: string;
  };
  sidebar: {
    runtime: string;
    title: string;
    demoCompanies: string;
    companies: string[];
  };
  chat: {
    title: string;
    apiReady: string;
    apiOffline: string;
    modelRunning: string;
    modelCompleted: (provider: string, model: string | null) => string;
    modelUnavailable: string;
    analysisCompleted: string;
    previousPage: string;
    nextPage: string;
    scrollNavigation: string;
    historyTitle: string;
    historyCollapse: string;
    historyExpand: string;
    historyLoading: string;
    historyEmpty: string;
    historyLoadError: string;
    historyDraft: string;
    historyDraftHint: string;
    historyConversation: (date: string) => string;
    historyMessageCount: (count: number) => string;
    historySelecting: string;
    historyClear: string;
    historyClearing: string;
    historyClearConfirm: (count: number) => string;
    historyClearError: string;
    reportTitle: string;
    reportQuestion: string;
    modelAnswer: string;
    modelAnswerDescription: string;
    agentEvidenceAnalysis: string;
    agentEvidenceDescription: string;
    analysisDetails: string;
    evidenceSources: string;
    evidenceReference: (index: number) => string;
    evidenceUsed: string;
    reasoningDetails: string;
    intent: string;
    companies: string;
    researchMode: string;
    workflow: string;
    strategy: string;
    provider: string;
    model: string;
    executionTime: string;
    emptyTitle: string;
    emptyDescription: string;
    demoPrompt: string;
    loading: string;
    placeholder: string;
    inputLabel: string;
    send: string;
    attachPdf: string;
    uploadingDocument: (filename: string) => string;
    documentSaved: (filename: string) => string;
    documentUploadFailed: (filename: string, detail: string) => string;
    user: string;
    assistant: string;
    connectionError: string;
    providerConfigurationError: string;
    providerDisabled: string;
    providerTemporaryError: string;
    runtimeFallbackError: string;
    answerDisclaimer: string;
    autoDiscoverySearching: (company: string) => string;
    autoDiscoveryDownloaded: (company: string) => string;
    autoDiscoveryAlreadyPresent: (company: string) => string;
    autoDiscoveryUnavailable: (company: string) => string;
    demoQuestions: Array<{ label: string; question: string }>;
  };
  agent: {
    title: string;
    empty: string;
    workflow: string;
    notAvailable: string;
    unclassified: string;
    runtime: string;
    runtimeFailed: string;
    structuredFact: string;
    structuredFactCompleted: string;
    provider: string;
    providerFailed: string;
    providerDisabled: string;
    intentAnalyzer: string;
    queryPlanner: string;
    hybridRetriever: string;
    evidenceRanking: string;
    llmGeneration: string;
    classifyingIntent: string;
    buildingPlan: string;
    searchingKnowledge: string;
    waitingForRetrieval: string;
    waitingForEvidence: string;
    classifiesIntent: string;
    buildsPlan: string;
    searchesEvidence: string;
    ranksEvidence: string;
    generatesReport: string;
    detectedIntent: (intent: string, companies: string[]) => string;
    executedSteps: (count: number) => string;
    builtPlan: string;
    planForWorkflow: (plan: string, workflow: string) => string;
    retrievedEvidence: (count: number) => string;
    rankedResults: string;
    generatedReport: (provider: string, strategy: string, executionTime: string) => string;
    status: {
      completed: string;
      safe_refusal: string;
      running: string;
      pending: string;
      failed: string;
    };
  };
  citations: {
    title: string;
    empty: string;
    sourceCount: (count: number) => string;
    source: string;
    sourceFallback: (index: number) => string;
    collapse: string;
    viewContext: string;
    similarityUnavailable: string;
    confidence: {
      high: string;
      medium: string;
      low: string;
    };
  };
  knowledge: {
    title: string;
    subtitle: string;
    refreshTitle: string;
    refresh: string;
    refreshing: string;
    total: string;
    indexed: string;
    processing: string;
    failed: string;
    searchPlaceholder: string;
    searchLabel: string;
    documents: string;
    connectionError: string;
    emptyTitle: string;
    emptyHint: string;
    company: string;
    pages: string;
    size: string;
    uploaded: string;
    period: string;
    chunks: string;
    checksum: string;
    viewSource: string;
    viewCninfoSource: string;
    delete: string;
    deleting: string;
    deleteDocument: (filename: string) => string;
    deleteConfirm: (filename: string) => string;
    deleteSuccess: (filename: string) => string;
    deleteFailed: string;
    quotaBypassed: string;
    status: {
      indexed: string;
      processing: string;
      failed: string;
      quarantined: string;
    };
  };
  upload: {
    title: string;
    ariaLabel: string;
    idle: string;
    uploading: string;
    success: string;
    error: string;
    hint: string;
    chooseFile: string;
    uploadAnother: string;
    retry: string;
    fallbackError: string;
    selectedFiles: (count: number) => string;
    batchSuccess: (count: number) => string;
    batchPartial: (success: number, failed: number) => string;
    duplicateDocument: string;
    invalidFileType: string;
    fileTooLarge: string;
    invalidDocument: string;
    uploadLimitExceeded: string;
    rateLimited: string;
  };
  retrieval: {
    queryFailed: string;
    queryPlaceholder: string;
    queryLabel: string;
    searching: string;
    search: string;
    queryHint: string;
    metricsTitle: string;
    latency: string;
    chunksRetrieved: string;
    retrieverType: string;
    resultsTitle: string;
    resultCount: (count: number) => string;
    page: string;
    source: string;
    similarity: string;
    emptyTitle: string;
    emptyHint: string;
  };
  document: {
    loadFailed: string;
    loadFailedTitle: string;
    backToDocuments: string;
    backToKnowledge: string;
    company: string;
    pages: string;
    statusLabel: string;
    size: string;
    uploaded: string;
    status: {
      indexed: string;
      processing: string;
      failed: string;
      quarantined: string;
    };
    statistics: string;
    chunks: string;
    embeddingStatus: string;
    vectorStatus: string;
    embedding: {
      completed: string;
      pending: string;
      failed: string;
    };
    vector: {
      stored: string;
      pending: string;
      failed: string;
    };
    chunkExplorer: string;
    chunk: (index: number) => string;
    noChunks: string;
    noChunksHint: string;
  };
  settings: {
    title: string;
    subtitle: string;
    appearanceTitle: string;
    appearanceDescription: string;
    themeLabel: string;
    lightTheme: string;
    lightThemeDescription: string;
    darkTheme: string;
    darkThemeDescription: string;
    languageTitle: string;
    languageDescription: string;
    llmTitle: string;
    llmDescription: string;
    securityNote: string;
    loading: string;
    loadError: string;
    retry: string;
    noProviders: string;
    configured: string;
    notConfigured: string;
    defaultProvider: string;
    defaultSelectionTitle: string;
    defaultSelectionDescription: string;
    defaultSelectionLabel: string;
    defaultSelectionValue: (provider: string, index: number, total: number) => string;
    defaultSelectionSaving: string;
    defaultSelectionSaved: string;
    defaultSelectionFailed: string;
    defaultSelectionUseSingle: string;
    keyHint: string;
    localEndpointLabel: string;
    localEndpointPlaceholder: string;
    localEndpointHelp: string;
    localModelLabel: string;
    localModelPlaceholder: string;
    localModelHelp: string;
    apiKeyLabel: string;
    apiKeyPlaceholder: string;
    modelLabel: string;
    modelPlaceholder: string;
    updatedAt: string;
    neverUpdated: string;
    save: string;
    saving: string;
    saved: string;
    clear: string;
    clearing: string;
    confirmClear: string;
    confirmClearLocal: string;
    confirmClearDescription: string;
    cancel: string;
    cleared: string;
    saveError: string;
    clearError: string;
  };
  errorBoundary: {
    title: string;
    unexpected: string;
    returnToChat: string;
  };
}

export const translations: Record<Language, Translation> = {
  en: {
    documentTitle: 'Financial RAG Assistant',
    language: {
      label: 'Language',
      english: 'English',
      chinese: 'Chinese',
    },
    app: {
      restoringSession: 'Restoring your session...',
      nav: {
        newChat: 'New chat',
        chat: 'Chat',
        knowledge: 'Knowledge',
        retrieval: 'Retrieval',
        settings: 'Settings',
        logout: 'Logout',
      },
    },
    auth: {
      eyebrow: 'Financial Agent Runtime',
      loginTitle: 'Welcome back',
      registerTitle: 'Create your account',
      loginSubtitle: 'Sign in to your Financial RAG workspace.',
      registerSubtitle: 'Register to upload and analyze financial documents.',
      modeLabel: 'Authentication mode',
      login: 'Login',
      register: 'Register',
      name: 'Name',
      email: 'Email',
      password: 'Password',
      failed: 'Authentication failed.',
      creatingAccount: 'Creating account...',
      signingIn: 'Signing in...',
      createAccount: 'Create account',
      signIn: 'Sign in',
    },
    header: {
      title: 'Financial RAG Assistant',
      chatSubtitle: 'AI Research Agent',
      knowledgeSubtitle: 'Knowledge Workspace',
      retrievalSubtitle: 'Retrieval Playground',
      documentSubtitle: 'Document Detail',
      settingsSubtitle: 'Workspace Settings',
      systemStatus: 'System status',
      connected: 'Connected',
      offline: 'Offline',
    },
    sidebar: {
      runtime: 'Financial Agent Runtime',
      title: 'AI Copilot',
      demoCompanies: 'Demo Companies',
      companies: ['Tesla', 'NVIDIA', 'Apple'],
    },
    chat: {
      title: 'Financial AI Copilot',
      apiReady: 'API ready',
      apiOffline: 'API offline',
      modelRunning: 'Calling model...',
      modelCompleted: (provider, model) =>
        model ? `Completed with ${provider} · ${model}` : `Completed with ${provider}`,
      modelUnavailable: 'Model unavailable',
      analysisCompleted: 'Agent analysis completed',
      previousPage: 'Previous page',
      nextPage: 'Next page',
      scrollNavigation: 'Answer scroll controls',
      historyTitle: 'Conversation history',
      historyCollapse: 'Collapse conversation history',
      historyExpand: 'Expand conversation history',
      historyLoading: 'Loading conversations...',
      historyEmpty: 'Completed conversations will appear here.',
      historyLoadError: 'Conversation history could not be loaded.',
      historyDraft: 'New conversation',
      historyDraftHint: 'Not saved until you send a message',
      historyConversation: (date) => `Conversation · ${date}`,
      historyMessageCount: (count) => `${count} messages`,
      historySelecting: 'Opening conversation...',
      historyClear: 'Clear',
      historyClearing: 'Clearing...',
      historyClearConfirm: (count) =>
        `Clear all ${count} conversations? Their messages will be permanently deleted. This cannot be undone.`,
      historyClearError:
        'Some conversations could not be cleared. The list has been refreshed.',
      reportTitle: 'Financial research report',
      reportQuestion: 'Research question',
      modelAnswer: 'Model answer',
      modelAnswerDescription: 'Generated by the routed language model.',
      agentEvidenceAnalysis: 'Agent evidence analysis',
      agentEvidenceDescription:
        'Deterministic facts, risks, conclusions, and source coverage assembled from retrieved evidence.',
      analysisDetails: 'Research context and Agent details',
      evidenceSources: 'Sources',
      evidenceReference: (index) => `Evidence ${index}`,
      evidenceUsed: 'Evidence used by the model',
      reasoningDetails: 'Execution details',
      intent: 'Intent',
      companies: 'Companies',
      researchMode: 'Research mode',
      workflow: 'Workflow',
      strategy: 'Strategy',
      provider: 'Provider',
      model: 'Model',
      executionTime: 'Execution time',
      emptyTitle: 'Turn financial reports into insight.',
      emptyDescription:
        'Ask a question, compare companies, or attach a report. Explore the analysis alongside its sources.',
      demoPrompt: 'Try a demo question',
      loading: 'Agent Runtime is analyzing...',
      placeholder: 'Ask a financial question...',
      inputLabel: 'Financial question input',
      send: 'Send',
      attachPdf: 'Upload a PDF to the knowledge base',
      uploadingDocument: (filename) =>
        `Uploading and indexing ${filename}...`,
      documentSaved: (filename) =>
        `${filename} is saved to the knowledge base and ready for retrieval.`,
      documentUploadFailed: (filename, detail) =>
        `Could not save ${filename}: ${detail}`,
      user: 'You',
      assistant: 'Assistant',
      connectionError: 'Connection error',
      providerConfigurationError:
        'AI provider credentials are not configured on the backend. Contact the deployment administrator and retry after provider authentication is enabled.',
      providerDisabled:
        'External AI calls are disabled by the runtime policy. No AI answer was generated. Ask an administrator to enable an approved provider or configure a local model.',
      providerTemporaryError:
        'The configured AI provider is temporarily unavailable. No answer was generated; check provider access and retry later.',
      runtimeFallbackError:
        'The agent could not complete this request. No verified answer was generated; check the runtime status before trying again.',
      answerDisclaimer: 'AI-generated results may be inaccurate. Please verify important data.',
      autoDiscoverySearching: (company) => `No filing evidence was found for ${company}. Searching SEC EDGAR...`,
      autoDiscoveryDownloaded: (company) => `The official filing for ${company} was downloaded and queued for indexing.`,
      autoDiscoveryAlreadyPresent: (company) => `${company} already has a filing in the knowledge base.`,
      autoDiscoveryUnavailable: (company) => `No trusted SEC filing could be downloaded for ${company}.`,
      demoQuestions: [
        {
          label: 'Tesla revenue growth',
          question: "What is Tesla's revenue growth trend in 2025?",
        },
        {
          label: 'NVIDIA data center',
          question: "How is NVIDIA's data center business performing?",
        },
        {
          label: 'Compare margins',
          question: 'Compare gross margins between Tesla and NVIDIA in 2025.',
        },
        {
          label: 'Apple services',
          question: "What is Apple's services revenue growth?",
        },
        {
          label: 'R&D investments',
          question: 'How much are Tesla and NVIDIA investing in R&D?',
        },
      ],
    },
    agent: {
      title: 'Agent Execution',
      empty: 'Submit a question to see the agent execution trace.',
      workflow: 'Workflow',
      notAvailable: 'N/A',
      unclassified: 'UNCLASSIFIED',
      runtime: 'Agent Runtime',
      runtimeFailed: 'The request stopped before a complete execution trace was produced.',
      structuredFact: 'Verified financial facts',
      structuredFactCompleted: 'Retrieved a verified financial fact with its source. No language model call was needed.',
      provider: 'LLM Provider',
      providerFailed: 'Provider authentication or configuration is unavailable.',
      providerDisabled: 'External provider calls are disabled by runtime policy.',
      intentAnalyzer: 'Intent Analyzer',
      queryPlanner: 'Query Planner',
      hybridRetriever: 'Hybrid Retriever',
      evidenceRanking: 'Evidence Ranking',
      llmGeneration: 'LLM Generation',
      classifyingIntent: 'Classifying user intent...',
      buildingPlan: 'Building research plan...',
      searchingKnowledge: 'Searching knowledge base...',
      waitingForRetrieval: 'Waiting for retrieval...',
      waitingForEvidence: 'Waiting for evidence...',
      classifiesIntent: 'Classifies the user query intent',
      buildsPlan: 'Builds a research execution plan',
      searchesEvidence: 'Searches vector store for evidence',
      ranksEvidence: 'Ranks results by relevance',
      generatesReport: 'Generates the final report',
      detectedIntent: (intent, companies) =>
        `Detected intent: ${intent}${companies.length ? ` — ${companies.join(', ')}` : ''}`,
      executedSteps: (count) => `Executed ${count} research step(s)`,
      builtPlan: 'Built research plan for analysis',
      planForWorkflow: (plan, workflow) => `${plan} for ${workflow} workflow`,
      retrievedEvidence: (count) =>
        `Retrieved ${count} evidence chunks from vector store`,
      rankedResults: 'Ranked results by relevance score',
      generatedReport: (provider, strategy, executionTime) =>
        `Generated report via ${provider} (${strategy}) in ${executionTime}`,
      status: {
        completed: 'Completed',
        safe_refusal: 'No answer generated',
        running: 'Running',
        pending: 'Pending',
        failed: 'Failed',
      },
    },
    citations: {
      title: 'Evidence',
      empty: 'Evidence will appear after analysis.',
      sourceCount: (count) => `${count} source${count === 1 ? '' : 's'}`,
      source: 'Source',
      sourceFallback: (index) => `Source ${index}`,
      collapse: 'Collapse',
      viewContext: 'View Context',
      similarityUnavailable: 'Similarity score unavailable',
      confidence: {
        high: 'High Confidence',
        medium: 'Medium Confidence',
        low: 'Low Confidence',
      },
    },
    knowledge: {
      title: 'Knowledge Workspace',
      subtitle: 'Financial Document Center',
      refreshTitle: 'Refresh knowledge base',
      refresh: 'Refresh',
      refreshing: 'Refreshing...',
      total: 'Total',
      indexed: 'Indexed',
      processing: 'Processing',
      failed: 'Failed',
      searchPlaceholder: 'Search documents by name or company...',
      searchLabel: 'Search documents',
      documents: 'Documents',
      connectionError: 'Connection error',
      emptyTitle: 'No documents yet',
      emptyHint: 'Upload a PDF document to add it to the knowledge base.',
      company: 'Company',
      pages: 'Pages',
      size: 'Size',
      uploaded: 'Uploaded',
      period: 'Period',
      chunks: 'Chunks',
      checksum: 'SHA-256',
      viewSource: 'View SEC source',
      viewCninfoSource: 'View CNINFO audited annual report',
      delete: 'Delete',
      deleting: 'Deleting...',
      deleteDocument: (filename) => `Delete ${filename}`,
      deleteConfirm: (filename) =>
        `Delete ${filename}? This removes its indexed evidence and uploaded file.`,
      deleteSuccess: (filename) => `${filename} was deleted.`,
      deleteFailed: 'Document deletion failed.',
      quotaBypassed: 'Evaluation mode: document quota is disabled; usage history is retained.',
      status: {
        indexed: 'Indexed',
        processing: 'Processing',
        failed: 'Failed',
        quarantined: 'Quarantined — queries blocked',
      },
    },
    upload: {
      title: 'Upload Document',
      ariaLabel: 'Upload financial report document',
      idle: 'Drag & drop a financial report, or click to browse',
      uploading: 'Uploading...',
      success: 'Upload complete!',
      error: 'Upload failed. Please try again.',
      hint: 'PDF, XLSX, DOCX or CSV · up to 50 MB each · select multiple files',
      chooseFile: 'Choose File',
      uploadAnother: 'Upload Another',
      retry: 'Retry',
      fallbackError: 'Upload failed.',
      selectedFiles: (count) => `${count} files selected`,
      batchSuccess: (count) => `${count} documents uploaded successfully.`,
      batchPartial: (success, failed) => `${success} uploaded, ${failed} failed.`,
      duplicateDocument: 'This document already exists in your workspace.',
      invalidFileType: 'Supported formats: PDF, XLSX, DOCX and CSV.',
      fileTooLarge: 'The file exceeds the 50 MB upload limit.',
      invalidDocument: 'The document is invalid, encrypted, or unsupported.',
      uploadLimitExceeded:
        'Your current document upload limit has been reached.',
      rateLimited: 'The upload service is busy. Please wait a moment and try again.',
    },
    retrieval: {
      queryFailed: 'Retrieval query failed.',
      queryPlaceholder: 'e.g. "Tesla revenue growth in 2025"',
      queryLabel: 'Retrieval query',
      searching: 'Searching...',
      search: 'Search',
      queryHint: 'Top 5 most relevant chunks will be retrieved from the knowledge base.',
      metricsTitle: 'Retrieval Metrics',
      latency: 'Latency',
      chunksRetrieved: 'Chunks Retrieved',
      retrieverType: 'Retriever Type',
      resultsTitle: 'Retrieved Chunks',
      resultCount: (count) => `${count} result${count === 1 ? '' : 's'}`,
      page: 'Page',
      source: 'Source',
      similarity: 'Similarity',
      emptyTitle: 'Retrieval Playground',
      emptyHint:
        'Enter a natural language query above to search the knowledge base. Results will show the most relevant chunks ranked by similarity score.',
    },
    document: {
      loadFailed: 'Failed to load document.',
      loadFailedTitle: 'Failed to Load Document',
      backToDocuments: 'Back to Documents',
      backToKnowledge: 'Back to Knowledge Workspace',
      company: 'Company',
      pages: 'Pages',
      statusLabel: 'Status',
      size: 'Size',
      uploaded: 'Uploaded',
      status: {
        indexed: 'Indexed',
        processing: 'Processing',
        failed: 'Failed',
        quarantined: 'Quarantined — queries blocked',
      },
      statistics: 'Document Statistics',
      chunks: 'Chunks',
      embeddingStatus: 'Embedding Status',
      vectorStatus: 'Vector Status',
      embedding: {
        completed: 'Completed',
        pending: 'Pending',
        failed: 'Failed',
      },
      vector: {
        stored: 'Stored',
        pending: 'Pending',
        failed: 'Failed',
      },
      chunkExplorer: 'Chunk Explorer',
      chunk: (index) => `Chunk #${index}`,
      noChunks: 'No chunks available',
      noChunksHint:
        'This document has not been chunked yet or the chunks are unavailable.',
    },
    settings: {
      title: 'Settings',
      subtitle: 'Manage appearance and LLM provider credentials for this workspace.',
      appearanceTitle: 'Appearance',
      appearanceDescription: 'Choose how the application looks on this device.',
      themeLabel: 'Color theme',
      lightTheme: 'Light',
      lightThemeDescription: 'A bright theme for daylight and high-contrast environments.',
      darkTheme: 'Dark',
      darkThemeDescription: 'A low-glare theme for focused work.',
      languageTitle: 'Language',
      languageDescription: 'Choose the language used by the application interface.',
      llmTitle: 'LLM Providers',
      llmDescription:
        'Configure provider credentials, choose a model version, and select the default runtime provider.',
      securityNote:
        'API keys are sent directly to the backend over the current connection. They are never stored in this browser or shown in full.',
      loading: 'Loading provider settings...',
      loadError: 'Provider settings could not be loaded.',
      retry: 'Retry',
      noProviders: 'No supported LLM providers are available.',
      configured: 'Configured',
      notConfigured: 'Not configured',
      defaultProvider: 'Default for new chats',
      defaultSelectionTitle: 'Default provider for new chats',
      defaultSelectionDescription: 'Configured means the connection details are saved; it does not mean the model process is running. This control chooses the provider used for new chats.',
      defaultSelectionLabel: 'Choose the default provider for new chats',
      defaultSelectionValue: (provider, index, total) => `${provider}, ${index} of ${total}`,
      defaultSelectionSaving: 'Updating default provider…',
      defaultSelectionSaved: 'Default provider updated.',
      defaultSelectionFailed: 'Could not update the default provider. The previous choice is still active.',
      defaultSelectionUseSingle: 'Use this configured provider for new chats',
      keyHint: 'Stored key',
      localEndpointLabel: 'Local Ollama endpoint',
      localEndpointPlaceholder: 'http://host.docker.internal:11434',
      localEndpointHelp: 'For Docker Desktop, use host.docker.internal to reach Ollama running on the host. Local HTTP endpoints only.',
      localModelLabel: 'Installed model tag',
      localModelPlaceholder: 'For example: qwen3.8:latest',
      localModelHelp: 'Enter the exact tag shown by `ollama list` on the machine running Ollama.',
      apiKeyLabel: 'API key',
      apiKeyPlaceholder: 'Enter a new API key',
      modelLabel: 'Model',
      modelPlaceholder: 'Use the provider default',
      updatedAt: 'Last updated',
      neverUpdated: 'Never',
      save: 'Save changes',
      saving: 'Saving...',
      saved: 'Provider settings saved.',
      clear: 'Clear configuration',
      clearing: 'Clearing...',
      confirmClear: 'Clear this API key?',
      confirmClearLocal: 'Clear this local model configuration?',
      confirmClearDescription:
        'Requests using this provider will stop working until a new key is saved.',
      cancel: 'Cancel',
      cleared: 'Provider key cleared.',
      saveError: 'Could not save the provider settings.',
      clearError: 'Could not clear the provider key.',
    },
    errorBoundary: {
      title: 'Something went wrong',
      unexpected: 'An unexpected error occurred.',
      returnToChat: 'Return to Chat',
    },
  },
  'zh-CN': {
    documentTitle: '金融 RAG 助手',
    language: {
      label: '语言',
      english: '英文',
      chinese: '中文',
    },
    app: {
      restoringSession: '正在恢复登录状态...',
      nav: {
        newChat: '新建对话',
        chat: '对话',
        knowledge: '知识库',
        retrieval: '检索',
        settings: '设置',
        logout: '退出登录',
      },
    },
    auth: {
      eyebrow: '金融智能体运行平台',
      loginTitle: '欢迎回来',
      registerTitle: '创建账户',
      loginSubtitle: '登录您的金融 RAG 工作空间。',
      registerSubtitle: '注册后即可上传和分析金融文档。',
      modeLabel: '认证方式',
      login: '登录',
      register: '注册',
      name: '姓名',
      email: '邮箱',
      password: '密码',
      failed: '认证失败。',
      creatingAccount: '正在创建账户...',
      signingIn: '正在登录...',
      createAccount: '创建账户',
      signIn: '登录',
    },
    header: {
      title: '金融 RAG 助手',
      chatSubtitle: 'AI 研究智能体',
      knowledgeSubtitle: '知识库工作空间',
      retrievalSubtitle: '检索实验室',
      documentSubtitle: '文档详情',
      settingsSubtitle: '工作空间设置',
      systemStatus: '系统状态',
      connected: '已连接',
      offline: '离线',
    },
    sidebar: {
      runtime: '金融智能体运行平台',
      title: 'AI Copilot',
      demoCompanies: '演示公司',
      companies: ['特斯拉', '英伟达', '苹果'],
    },
    chat: {
      title: '金融 AI Copilot',
      apiReady: 'API 已就绪',
      apiOffline: 'API 离线',
      modelRunning: '正在调用模型...',
      modelCompleted: (provider, model) =>
        model ? `已由 ${provider} · ${model} 完成` : `已由 ${provider} 完成`,
      modelUnavailable: '模型不可用',
      analysisCompleted: '智能体分析已完成',
      previousPage: '上一页',
      nextPage: '下一页',
      scrollNavigation: '回答滚动控制',
      historyTitle: '对话历史',
      historyCollapse: '向左收起对话历史',
      historyExpand: '向右展开对话历史',
      historyLoading: '正在加载历史对话...',
      historyEmpty: '完成一次对话后，历史记录会显示在这里。',
      historyLoadError: '暂时无法加载对话历史。',
      historyDraft: '新对话',
      historyDraftHint: '发送消息后保存',
      historyConversation: (date) => `对话 · ${date}`,
      historyMessageCount: (count) => `${count} 条消息`,
      historySelecting: '正在打开对话...',
      historyClear: '清空',
      historyClearing: '清空中...',
      historyClearConfirm: (count) =>
        `确认清空全部 ${count} 个对话？其中的消息将被永久删除，此操作无法撤销。`,
      historyClearError: '部分对话未能清除，列表已按服务器状态刷新。',
      reportTitle: '金融研究报告',
      reportQuestion: '研究问题',
      modelAnswer: '模型回答',
      modelAnswerDescription: '由实际路由到的大语言模型生成。',
      agentEvidenceAnalysis: '智能体证据分析',
      agentEvidenceDescription:
        '智能体根据检索证据整理的事实、风险、结论与来源覆盖情况。',
      analysisDetails: '研究上下文与智能体详情',
      evidenceSources: '引用来源',
      evidenceReference: (index) => `证据 ${index}`,
      evidenceUsed: '模型使用的证据',
      reasoningDetails: '执行详情',
      intent: '意图',
      companies: '公司',
      researchMode: '研究模式',
      workflow: '工作流',
      strategy: '执行策略',
      provider: '服务提供方',
      model: '模型',
      executionTime: '执行时间',
      emptyTitle: '读懂财报，看清关键。',
      emptyDescription:
        '提出问题、比较公司，或上传一份财报。结合分析与来源，让每一次研究更有依据。',
      demoPrompt: '试试示例问题',
      loading: '智能体正在分析...',
      placeholder: '请输入金融问题...',
      inputLabel: '金融问题输入框',
      send: '发送',
      attachPdf: '上传 PDF 并保存到知识库',
      uploadingDocument: (filename) =>
        `正在上传并索引 ${filename}...`,
      documentSaved: (filename) =>
        `${filename} 已保存到知识库，并可用于检索。`,
      documentUploadFailed: (filename, detail) =>
        `${filename} 保存失败：${detail}`,
      user: '你',
      assistant: '助手',
      connectionError: '连接错误',
      providerConfigurationError:
        '后端尚未配置 AI 服务凭证。请联系部署管理员完成服务认证后重试。',
      providerDisabled:
        '当前运行策略已禁用外部 AI 服务调用，本次没有生成 AI 答案。请联系管理员启用获准的模型服务，或配置本地模型。',
      providerTemporaryError:
        '当前 AI 服务暂不可用，本次没有生成答案。请检查服务状态后再试。',
      runtimeFallbackError:
        '智能体未能完成本次请求，因此没有生成经过核实的答案。请先检查运行状态再重试。',
      answerDisclaimer: 'AI生成结果可能有误，请核实重要数据',
      autoDiscoverySearching: (company) => `未找到 ${company} 的财报证据，正在从 SEC EDGAR 查找...`,
      autoDiscoveryDownloaded: (company) => `已下载 ${company} 的官方财报并排队索引。`,
      autoDiscoveryAlreadyPresent: (company) => `知识库中已有 ${company} 的财报。`,
      autoDiscoveryUnavailable: (company) => `未能从可信 SEC 来源下载 ${company} 的财报。`,
      demoQuestions: [
        {
          label: '特斯拉营收增长',
          question: '特斯拉在 2025 年的营收增长趋势如何？',
        },
        {
          label: '英伟达数据中心',
          question: '英伟达的数据中心业务表现如何？',
        },
        {
          label: '比较毛利率',
          question: '比较特斯拉和英伟达在 2025 年的毛利率。',
        },
        {
          label: '苹果服务业务',
          question: '苹果服务业务的营收增长情况如何？',
        },
        {
          label: '研发投入',
          question: '特斯拉和英伟达分别投入了多少研发费用？',
        },
      ],
    },
    agent: {
      title: '智能体执行',
      empty: '提交问题后可查看智能体执行轨迹。',
      workflow: '工作流',
      notAvailable: '暂无',
      unclassified: '未分类',
      runtime: '智能体运行时',
      runtimeFailed: '请求在生成完整执行轨迹前终止。',
      structuredFact: '已验证财务事实',
      structuredFactCompleted: '已检索到带来源的财务事实，本次无需调用大模型。',
      provider: '大模型服务',
      providerFailed: '大模型服务认证或配置不可用。',
      providerDisabled: '外部模型调用已被当前运行策略禁用。',
      intentAnalyzer: '意图分析',
      queryPlanner: '查询规划',
      hybridRetriever: '混合检索',
      evidenceRanking: '证据排序',
      llmGeneration: '大模型生成',
      classifyingIntent: '正在识别用户意图...',
      buildingPlan: '正在构建研究计划...',
      searchingKnowledge: '正在检索知识库...',
      waitingForRetrieval: '正在等待检索结果...',
      waitingForEvidence: '正在等待证据...',
      classifiesIntent: '识别用户查询意图',
      buildsPlan: '构建研究执行计划',
      searchesEvidence: '从向量库检索证据',
      ranksEvidence: '按相关性排序结果',
      generatesReport: '生成最终分析报告',
      detectedIntent: (intent, companies) =>
        `识别意图：${intent}${companies.length ? ` — ${companies.join('、')}` : ''}`,
      executedSteps: (count) => `已执行 ${count} 个研究步骤`,
      builtPlan: '已构建分析研究计划',
      planForWorkflow: (plan, workflow) => `${plan}，工作流：${workflow}`,
      retrievedEvidence: (count) => `已从向量库检索 ${count} 条证据`,
      rankedResults: '已按相关性对结果排序',
      generatedReport: (provider, strategy, executionTime) =>
        `已通过 ${provider}（${strategy}）生成报告，用时 ${executionTime}`,
      status: {
        completed: '已完成',
        safe_refusal: '未生成答案',
        running: '运行中',
        pending: '等待中',
        failed: '失败',
      },
    },
    citations: {
      title: '证据',
      empty: '分析完成后将在此显示证据。',
      sourceCount: (count) => `${count} 个来源`,
      source: '来源',
      sourceFallback: (index) => `来源 ${index}`,
      collapse: '收起',
      viewContext: '查看上下文',
      similarityUnavailable: '暂无相似度分数',
      confidence: {
        high: '高置信度',
        medium: '中等置信度',
        low: '低置信度',
      },
    },
    knowledge: {
      title: '知识库工作空间',
      subtitle: '金融文档中心',
      refreshTitle: '刷新知识库',
      refresh: '刷新',
      refreshing: '正在刷新...',
      total: '总计',
      indexed: '已索引',
      processing: '处理中',
      failed: '失败',
      searchPlaceholder: '按文件名或公司搜索文档...',
      searchLabel: '搜索文档',
      documents: '文档',
      connectionError: '连接错误',
      emptyTitle: '暂无文档',
      emptyHint: '上传 PDF 文档后即可添加到知识库。',
      company: '公司',
      pages: '页数',
      size: '大小',
      uploaded: '上传于',
      period: '报告期',
      chunks: '文本块',
      checksum: 'SHA-256',
      viewSource: '查看 SEC 来源',
      viewCninfoSource: '查看巨潮资讯审计年报',
      delete: '删除',
      deleting: '正在删除...',
      deleteDocument: (filename) => `删除 ${filename}`,
      deleteConfirm: (filename) =>
        `确认删除 ${filename}？其索引证据和上传文件也会被删除。`,
      deleteSuccess: (filename) => `已删除 ${filename}。`,
      deleteFailed: '删除文档失败。',
      quotaBypassed: '评测模式：文档额度已关闭，历史使用记录仍会保留。',
      status: {
        indexed: '已索引',
        processing: '处理中',
        failed: '失败',
        quarantined: '已隔离，禁止查询',
      },
    },
    upload: {
      title: '上传文档',
      ariaLabel: '上传财务报告',
      idle: '将财务报告拖放到此处，或点击浏览',
      uploading: '正在上传...',
      success: '上传完成！',
      error: '上传失败，请重试。',
      hint: '支持 PDF、XLSX、DOCX、CSV；单份最大 50 MB，可一次选择多份',
      chooseFile: '选择文件',
      uploadAnother: '继续上传',
      retry: '重试',
      fallbackError: '上传失败。',
      selectedFiles: (count) => `已选择 ${count} 个文件`,
      batchSuccess: (count) => `已成功上传 ${count} 份文档。`,
      batchPartial: (success, failed) => `成功 ${success} 份，失败 ${failed} 份。`,
      duplicateDocument: '此文档已存在于当前工作空间。',
      invalidFileType: '支持格式：PDF、XLSX、DOCX、CSV。',
      fileTooLarge: '文件超过 50 MB 上传限制。',
      invalidDocument: '文件无效、已加密或暂不受支持。',
      uploadLimitExceeded: '当前工作空间的文档上传额度已用完。',
      rateLimited: '上传服务当前请求较多，请稍后重试。',
    },
    retrieval: {
      queryFailed: '检索查询失败。',
      queryPlaceholder: '例如：“特斯拉 2025 年营收增长”',
      queryLabel: '检索查询',
      searching: '正在检索...',
      search: '检索',
      queryHint: '将从知识库中检索相关性最高的 5 个文本块。',
      metricsTitle: '检索指标',
      latency: '延迟',
      chunksRetrieved: '检索文本块',
      retrieverType: '检索器类型',
      resultsTitle: '检索结果',
      resultCount: (count) => `${count} 条结果`,
      page: '页码',
      source: '来源',
      similarity: '相似度',
      emptyTitle: '检索实验室',
      emptyHint:
        '在上方输入自然语言问题以检索知识库。结果将按相似度展示最相关的文本块。',
    },
    document: {
      loadFailed: '文档加载失败。',
      loadFailedTitle: '无法加载文档',
      backToDocuments: '返回文档列表',
      backToKnowledge: '返回知识库工作空间',
      company: '公司',
      pages: '页数',
      statusLabel: '状态',
      size: '大小',
      uploaded: '上传于',
      status: {
        indexed: '已索引',
        processing: '处理中',
        failed: '失败',
        quarantined: '已隔离，禁止查询',
      },
      statistics: '文档统计',
      chunks: '文本块',
      embeddingStatus: '嵌入状态',
      vectorStatus: '向量状态',
      embedding: {
        completed: '已完成',
        pending: '等待中',
        failed: '失败',
      },
      vector: {
        stored: '已存储',
        pending: '等待中',
        failed: '失败',
      },
      chunkExplorer: '文本块浏览',
      chunk: (index) => `文本块 #${index}`,
      noChunks: '暂无文本块',
      noChunksHint: '该文档尚未完成分块，或当前无法获取文本块。',
    },
    settings: {
      title: '设置',
      subtitle: '管理当前工作空间的界面外观和大模型服务凭证。',
      appearanceTitle: '外观',
      appearanceDescription: '选择此设备上的应用显示风格。',
      themeLabel: '颜色主题',
      lightTheme: '浅色',
      lightThemeDescription: '适合日间和明亮环境的高对比度界面。',
      darkTheme: '深色',
      darkThemeDescription: '适合专注工作的低眩光界面。',
      languageTitle: '语言',
      languageDescription: '选择应用界面使用的语言。',
      llmTitle: '大模型服务',
      llmDescription: '配置服务凭证、选择模型版本，并指定运行时默认使用的大模型服务。',
      securityNote:
        'API Key 会通过当前连接直接发送到后端，不会存储在浏览器中，也不会在界面完整显示。',
      loading: '正在加载服务配置...',
      loadError: '无法加载大模型服务配置。',
      retry: '重试',
      noProviders: '当前没有可配置的大模型服务。',
      configured: '已配置',
      notConfigured: '未配置',
      defaultProvider: '新对话默认',
      defaultSelectionTitle: '新对话默认服务',
      defaultSelectionDescription: '“已配置”表示服务参数已保存，不代表模型进程正在运行。此处选择新对话使用的服务。',
      defaultSelectionLabel: '选择新对话默认使用的服务',
      defaultSelectionValue: (provider, index, total) => `${provider}，第 ${index} 项，共 ${total} 项`,
      defaultSelectionSaving: '正在更新默认服务…',
      defaultSelectionSaved: '新对话默认服务已更新。',
      defaultSelectionFailed: '无法更新默认服务，原选择保持不变。',
      defaultSelectionUseSingle: '将此已配置服务用于新对话',
      keyHint: '已保存密钥',
      localEndpointLabel: '本地 Ollama 服务地址',
      localEndpointPlaceholder: 'http://host.docker.internal:11434',
      localEndpointHelp: 'Docker Desktop 中连接宿主机 Ollama 通常使用 host.docker.internal。仅允许本地 HTTP 地址。',
      localModelLabel: '已安装的模型标签',
      localModelPlaceholder: '例如：qwen3.8:latest',
      localModelHelp: '请填写 Ollama 所在机器上 `ollama list` 显示的完整模型标签。',
      apiKeyLabel: 'API Key',
      apiKeyPlaceholder: '输入新的 API Key',
      modelLabel: '模型',
      modelPlaceholder: '使用服务默认模型',
      updatedAt: '最后更新',
      neverUpdated: '从未',
      save: '保存更改',
      saving: '正在保存...',
      saved: '服务配置已保存。',
      clear: '清除配置',
      clearing: '正在清除...',
      confirmClear: '确认清除此 API Key？',
      confirmClearLocal: '确认清除此本地模型配置？',
      confirmClearDescription: '保存新密钥前，使用此服务的请求将无法执行。',
      cancel: '取消',
      cleared: '服务配置已清除。',
      saveError: '无法保存服务配置。',
      clearError: '无法清除服务密钥。',
    },
    errorBoundary: {
      title: '页面出现问题',
      unexpected: '发生了意外错误。',
      returnToChat: '返回对话',
    },
  },
};
