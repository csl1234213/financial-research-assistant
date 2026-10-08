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
    documentTitle: 'Financial Research Assistant',
    language: {
      label: 'Language',
      english: 'English',
      chinese: 'Chinese',
    },
    app: {
      restoringSession: 'Restoring your session...',
      nav: {
        newChat: 'New chat',
        chat: 'Ask',
        knowledge: 'Documents',
        retrieval: 'Search',
        settings: 'Settings',
        logout: 'Sign Out',
      },
    },
    auth: {
      eyebrow: 'Financial Research',
      loginTitle: 'Welcome back',
      registerTitle: 'Create your account',
      loginSubtitle: 'Sign in to continue your research.',
      registerSubtitle: 'Create an account to upload and explore documents.',
      modeLabel: 'Sign-in Options',
      login: 'Sign In',
      register: 'Sign Up',
      name: 'Name',
      email: 'Email',
      password: 'Password',
      failed: 'Sign-in failed. Check your email and password.',
      creatingAccount: 'Creating account...',
      signingIn: 'Signing in...',
      createAccount: 'Create account',
      signIn: 'Sign in',
    },
    header: {
      title: 'Financial Research Assistant',
      chatSubtitle: 'Report Assistant',
      knowledgeSubtitle: 'Document Library',
      retrievalSubtitle: 'Document Search',
      documentSubtitle: 'Document Detail',
      settingsSubtitle: 'Settings',
      systemStatus: 'System status',
      connected: 'Connected',
      offline: 'Offline',
    },
    sidebar: {
      runtime: 'Financial Research',
      title: 'Report Assistant',
      demoCompanies: 'Demo Companies',
      companies: ['Tesla', 'NVIDIA', 'Apple'],
    },
    chat: {
      title: 'Report Assistant',
      apiReady: 'Connected',
      apiOffline: 'Disconnected',
      modelRunning: 'Writing your answer...',
      modelCompleted: (provider, model) =>
        model ? `Completed with ${provider} · ${model}` : `Completed with ${provider}`,
      modelUnavailable: 'Service Unavailable',
      analysisCompleted: 'Analysis Complete',
      previousPage: 'Previous page',
      nextPage: 'Next page',
      scrollNavigation: 'Answer scroll controls',
      historyTitle: 'Past Chats',
      historyCollapse: 'Hide History',
      historyExpand: 'Show History',
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
      reportTitle: 'Research Results',
      reportQuestion: 'Your Question',
      modelAnswer: 'AI Answer',
      modelAnswerDescription: 'Generated by your selected AI service.',
      agentEvidenceAnalysis: 'Document Analysis',
      agentEvidenceDescription:
        'Findings and source coverage based on retrieved document passages.',
      analysisDetails: 'Answer Details',
      evidenceSources: 'Sources',
      evidenceReference: (index) => `Evidence ${index}`,
      evidenceUsed: 'Supporting Sources',
      reasoningDetails: 'Processing Details',
      intent: 'Question Type',
      companies: 'Companies',
      researchMode: 'Analysis Method',
      workflow: 'Process',
      strategy: 'Processing Method',
      provider: 'AI Service',
      model: 'Model',
      executionTime: 'Time Taken',
      emptyTitle: 'Understand Your Reports',
      emptyDescription:
        'Upload a report, ask questions, and check the sources.',
      demoPrompt: 'Example Questions',
      loading: 'Working on your question...',
      placeholder: 'Ask about your documents...',
      inputLabel: 'Your Question',
      send: 'Send',
      attachPdf: 'Add Document',
      uploadingDocument: (filename) =>
        `Uploading and indexing ${filename}...`,
      documentSaved: (filename) =>
        `${filename} is saved and available for search.`,
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
      title: 'Processing Steps',
      empty: 'Ask a question to see the processing steps.',
      workflow: 'Process',
      notAvailable: 'N/A',
      unclassified: 'UNCLASSIFIED',
      runtime: 'Question Processing',
      runtimeFailed: 'The request stopped before a complete execution trace was produced.',
      structuredFact: 'Financial Data',
      structuredFactCompleted: 'Retrieved a verified financial fact with its source. No language model call was needed.',
      provider: 'AI Service',
      providerFailed: 'Provider authentication or configuration is unavailable.',
      providerDisabled: 'External provider calls are disabled by runtime policy.',
      intentAnalyzer: 'Understand Question',
      queryPlanner: 'Plan Steps',
      hybridRetriever: 'Find Sources',
      evidenceRanking: 'Rank Sources',
      llmGeneration: 'Write Answer',
      classifyingIntent: 'Understanding your question...',
      buildingPlan: 'Planning the steps...',
      searchingKnowledge: 'Searching your documents...',
      waitingForRetrieval: 'Waiting for search results...',
      waitingForEvidence: 'Waiting for sources...',
      classifiesIntent: 'Identifies what you want to know',
      buildsPlan: 'Arranges the processing steps',
      searchesEvidence: 'Finds relevant document passages',
      ranksEvidence: 'Puts relevant passages first',
      generatesReport: 'Writes the answer',
      detectedIntent: (intent, companies) =>
        `Detected intent: ${intent}${companies.length ? ` — ${companies.join(', ')}` : ''}`,
      executedSteps: (count) => `Executed ${count} research step(s)`,
      builtPlan: 'Processing steps planned',
      planForWorkflow: (plan, workflow) => `${plan} for ${workflow} workflow`,
      retrievedEvidence: (count) =>
        `Found ${count} supporting passages`,
      rankedResults: 'Sources ranked by relevance',
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
      title: 'Sources',
      empty: 'Evidence will appear after analysis.',
      sourceCount: (count) => `${count} source${count === 1 ? '' : 's'}`,
      source: 'Source',
      sourceFallback: (index) => `Source ${index}`,
      collapse: 'Collapse',
      viewContext: 'View Passage',
      similarityUnavailable: 'No match score available',
      confidence: {
        high: 'Strong Match',
        medium: 'Moderate Match',
        low: 'Weak Match',
      },
    },
    knowledge: {
      title: 'Document Library',
      subtitle: 'Uploaded Documents',
      refreshTitle: 'Refresh Documents',
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
      uploaded: 'Uploaded On',
      period: 'Report Period',
      chunks: 'Text Passages',
      checksum: 'File Fingerprint',
      viewSource: 'View Original',
      viewCninfoSource: 'View Original',
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
        quarantined: 'Unavailable — questions blocked',
      },
    },
    upload: {
      title: 'Upload Documents',
      ariaLabel: 'Upload financial report document',
      idle: 'Choose files or drag them here',
      uploading: 'Uploading...',
      success: 'Upload Complete',
      error: 'Upload failed. Please try again.',
      hint: 'PDF, XLSX, DOCX or CSV · up to 50 MB each · select multiple files',
      chooseFile: 'Choose File',
      uploadAnother: 'Upload More',
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
      queryFailed: 'Search failed. Please try again.',
      queryPlaceholder: 'e.g. "Tesla revenue growth in 2025"',
      queryLabel: 'Search Terms',
      searching: 'Searching...',
      search: 'Search',
      queryHint: 'Find up to five relevant passages in your documents.',
      metricsTitle: 'Search Details',
      latency: 'Search Time',
      chunksRetrieved: 'Passages Found',
      retrieverType: 'Search Method',
      resultsTitle: 'Search Results',
      resultCount: (count) => `${count} result${count === 1 ? '' : 's'}`,
      page: 'Page',
      source: 'Source',
      similarity: 'Match Score',
      emptyTitle: 'Document Search',
      emptyHint:
        'Search your documents for passages matching your question.',
    },
    document: {
      loadFailed: 'Failed to load document.',
      loadFailedTitle: 'Document Unavailable',
      backToDocuments: 'Back to Documents',
      backToKnowledge: 'Back to Documents',
      company: 'Company',
      pages: 'Pages',
      statusLabel: 'Status',
      size: 'Size',
      uploaded: 'Uploaded On',
      status: {
        indexed: 'Indexed',
        processing: 'Processing',
        failed: 'Failed',
        quarantined: 'Unavailable — questions blocked',
      },
      statistics: 'Document Details',
      chunks: 'Text Passages',
      embeddingStatus: 'Search Preparation',
      vectorStatus: 'Search Storage',
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
      chunkExplorer: 'Browse Text',
      chunk: (index) => `Passage #${index}`,
      noChunks: 'No Text Available',
      noChunksHint:
        'Document processing is incomplete or its text is unavailable.',
    },
    settings: {
      title: 'Settings',
      subtitle: 'Manage appearance and AI service settings.',
      appearanceTitle: 'Appearance',
      appearanceDescription: 'Choose how the application looks on this device.',
      themeLabel: 'Theme',
      lightTheme: 'Light',
      lightThemeDescription: 'A bright theme for daylight and high-contrast environments.',
      darkTheme: 'Dark',
      darkThemeDescription: 'A low-glare theme for focused work.',
      languageTitle: 'Language',
      languageDescription: 'Choose the language used by the application interface.',
      llmTitle: 'AI Services',
      llmDescription:
        'Set up AI services and choose one for new chats.',
      securityNote:
        'API keys are sent directly to the backend over the current connection. They are never stored in this browser or shown in full.',
      loading: 'Loading service settings...',
      loadError: 'Service settings could not be loaded.',
      retry: 'Retry',
      noProviders: 'No AI services are available for setup.',
      configured: 'Settings Saved',
      notConfigured: 'Not Set Up',
      defaultProvider: 'Default Service',
      defaultSelectionTitle: 'Default Service',
      defaultSelectionDescription: 'Used for new chats. Saved settings do not mean the service is running.',
      defaultSelectionLabel: 'Choose a service for new chats',
      defaultSelectionValue: (provider, index, total) => `${provider}, ${index} of ${total}`,
      defaultSelectionSaving: 'Updating default provider…',
      defaultSelectionSaved: 'Default provider updated.',
      defaultSelectionFailed: 'Could not update the default provider. The previous choice is still active.',
      defaultSelectionUseSingle: 'Use this configured provider for new chats',
      keyHint: 'Key Saved',
      localEndpointLabel: 'Service Address',
      localEndpointPlaceholder: 'http://host.docker.internal:11434',
      localEndpointHelp: 'For Docker Desktop, use host.docker.internal to reach Ollama running on the host. Local HTTP endpoints only.',
      localModelLabel: 'Model Name',
      localModelPlaceholder: 'For example: qwen3.8:latest',
      localModelHelp: 'Enter the exact tag shown by `ollama list` on the machine running Ollama.',
      apiKeyLabel: 'API key',
      apiKeyPlaceholder: 'Enter a new API key',
      modelLabel: 'Model',
      modelPlaceholder: 'Service Default',
      updatedAt: 'Last updated',
      neverUpdated: 'Never',
      save: 'Save Settings',
      saving: 'Saving...',
      saved: 'Service settings saved.',
      clear: 'Clear Settings',
      clearing: 'Clearing...',
      confirmClear: 'Clear this API key?',
      confirmClearLocal: 'Clear this local model configuration?',
      confirmClearDescription:
        'Requests using this provider will stop working until a new key is saved.',
      cancel: 'Cancel',
      cleared: 'Service settings cleared.',
      saveError: 'Could not save service settings.',
      clearError: 'Could not clear the service key.',
    },
    errorBoundary: {
      title: 'Something went wrong',
      unexpected: 'An unexpected error occurred.',
      returnToChat: 'Back to Ask',
    },
  },
  'zh-CN': {
    documentTitle: '财报助手',
    language: {
      label: '语言',
      english: '英文',
      chinese: '中文',
    },
    app: {
      restoringSession: '正在恢复登录状态...',
      nav: {
        newChat: '新建问答',
        chat: '问答',
        knowledge: '文档',
        retrieval: '搜索',
        settings: '设置',
        logout: '退出登录',
      },
    },
    auth: {
      eyebrow: '金融研究',
      loginTitle: '欢迎回来',
      registerTitle: '注册账号',
      loginSubtitle: '登录后继续研究。',
      registerSubtitle: '注册后上传资料，开始提问。',
      modeLabel: '登录方式',
      login: '登录',
      register: '注册',
      name: '姓名',
      email: '邮箱',
      password: '密码',
      failed: '登录失败，请检查邮箱和密码。',
      creatingAccount: '正在创建账户...',
      signingIn: '正在登录...',
      createAccount: '注册账号',
      signIn: '登录',
    },
    header: {
      title: '财报助手',
      chatSubtitle: '财报问答',
      knowledgeSubtitle: '文档管理',
      retrievalSubtitle: '内容搜索',
      documentSubtitle: '文档详情',
      settingsSubtitle: '使用设置',
      systemStatus: '系统状态',
      connected: '已连接',
      offline: '离线',
    },
    sidebar: {
      runtime: '金融研究',
      title: '财报助手',
      demoCompanies: '演示公司',
      companies: ['特斯拉', '英伟达', '苹果'],
    },
    chat: {
      title: '财报问答',
      apiReady: '已连接',
      apiOffline: '未连接',
      modelRunning: '正在生成回答…',
      modelCompleted: (provider, model) =>
        model ? `已由 ${provider} · ${model} 完成` : `已由 ${provider} 完成`,
      modelUnavailable: '服务不可用',
      analysisCompleted: '分析完成',
      previousPage: '上一页',
      nextPage: '下一页',
      scrollNavigation: '回答滚动控制',
      historyTitle: '历史问答',
      historyCollapse: '收起历史',
      historyExpand: '展开历史',
      historyLoading: '正在加载历史对话...',
      historyEmpty: '完成一次对话后，历史记录会显示在这里。',
      historyLoadError: '暂时无法加载对话历史。',
      historyDraft: '新问答',
      historyDraftHint: '发送消息后保存',
      historyConversation: (date) => `对话 · ${date}`,
      historyMessageCount: (count) => `${count} 条消息`,
      historySelecting: '正在打开对话...',
      historyClear: '清空记录',
      historyClearing: '清空中...',
      historyClearConfirm: (count) =>
        `确认清空全部 ${count} 个对话？其中的消息将被永久删除，此操作无法撤销。`,
      historyClearError: '部分对话未能清除，列表已按服务器状态刷新。',
      reportTitle: '研究结果',
      reportQuestion: '当前问题',
      modelAnswer: 'AI 回答',
      modelAnswerDescription: '由所选 AI 服务生成。',
      agentEvidenceAnalysis: '资料分析',
      agentEvidenceDescription:
        '根据找到的资料整理事实和来源覆盖情况。',
      analysisDetails: '回答详情',
      evidenceSources: '回答出处',
      evidenceReference: (index) => `证据 ${index}`,
      evidenceUsed: '参考资料',
      reasoningDetails: '处理详情',
      intent: '问题类型',
      companies: '公司',
      researchMode: '分析方式',
      workflow: '处理流程',
      strategy: '处理方式',
      provider: '服务来源',
      model: '模型',
      executionTime: '处理耗时',
      emptyTitle: '读懂财报',
      emptyDescription:
        '上传资料，提问并查看出处。',
      demoPrompt: '示例问题',
      loading: '正在分析资料…',
      placeholder: '输入问题…',
      inputLabel: '问题输入',
      send: '发送',
      attachPdf: '添加文档',
      uploadingDocument: (filename) =>
        `正在上传并索引 ${filename}...`,
      documentSaved: (filename) =>
        `${filename} 已保存，可用于搜索。`,
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
        '本次处理失败，未生成经核对的回答。请检查运行状态后重试。',
      answerDisclaimer: 'AI 回答可能有误，请核对重要数据',
      autoDiscoverySearching: (company) => `未找到 ${company} 的财报证据，正在从 SEC EDGAR 查找...`,
      autoDiscoveryDownloaded: (company) => `已下载 ${company} 的官方财报并排队索引。`,
      autoDiscoveryAlreadyPresent: (company) => `文档中已有 ${company} 的财报。`,
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
      title: '处理过程',
      empty: '提问后可查看处理过程。',
      workflow: '处理流程',
      notAvailable: '暂无',
      unclassified: '未分类',
      runtime: '问题处理',
      runtimeFailed: '请求在生成完整执行轨迹前终止。',
      structuredFact: '财务数据',
      structuredFactCompleted: '已找到带出处的财务数据，无需 AI 生成。',
      provider: 'AI 服务',
      providerFailed: 'AI 服务密钥或设置不可用。',
      providerDisabled: '外部模型调用已被当前运行策略禁用。',
      intentAnalyzer: '理解问题',
      queryPlanner: '安排步骤',
      hybridRetriever: '查找资料',
      evidenceRanking: '整理资料',
      llmGeneration: '生成回答',
      classifyingIntent: '正在理解问题…',
      buildingPlan: '正在安排步骤…',
      searchingKnowledge: '正在查找资料…',
      waitingForRetrieval: '正在等待搜索结果…',
      waitingForEvidence: '正在等待资料…',
      classifiesIntent: '识别你想了解的内容',
      buildsPlan: '安排本次处理步骤',
      searchesEvidence: '从文档中查找相关内容',
      ranksEvidence: '将相关内容排在前面',
      generatesReport: '根据资料整理回答',
      detectedIntent: (intent, companies) =>
        `识别意图：${intent}${companies.length ? ` — ${companies.join('、')}` : ''}`,
      executedSteps: (count) => `已执行 ${count} 个研究步骤`,
      builtPlan: '已安排处理步骤',
      planForWorkflow: (plan, workflow) => `${plan}，工作流：${workflow}`,
      retrievedEvidence: (count) => `已找到 ${count} 段相关原文`,
      rankedResults: '已按相关程度整理资料',
      generatedReport: (provider, strategy, executionTime) =>
        `已通过 ${provider}（${strategy}）生成报告，用时 ${executionTime}`,
      status: {
        completed: '已完成',
        safe_refusal: '暂无回答',
        running: '处理中',
        pending: '等待处理',
        failed: '失败',
      },
    },
    citations: {
      title: '参考资料',
      empty: '分析完成后将在此显示证据。',
      sourceCount: (count) => `${count} 个来源`,
      source: '来源',
      sourceFallback: (index) => `来源 ${index}`,
      collapse: '收起',
      viewContext: '查看原文',
      similarityUnavailable: '暂无匹配分数',
      confidence: {
        high: '匹配较高',
        medium: '匹配一般',
        low: '匹配较低',
      },
    },
    knowledge: {
      title: '文档管理',
      subtitle: '文档列表',
      refreshTitle: '刷新列表',
      refresh: '刷新',
      refreshing: '正在刷新...',
      total: '文档总数',
      indexed: '已收录',
      processing: '处理中',
      failed: '失败',
      searchPlaceholder: '输入文件名或公司名称…',
      searchLabel: '搜索文档',
      documents: '文档',
      connectionError: '连接错误',
      emptyTitle: '暂无文档',
      emptyHint: '上传文件后会显示在这里。',
      company: '公司',
      pages: '页数',
      size: '大小',
      uploaded: '上传时间',
      period: '报告期间',
      chunks: '内容片段',
      checksum: 'SHA-256',
      viewSource: '查看原文',
      viewCninfoSource: '查看原文',
      delete: '删除',
      deleting: '正在删除...',
      deleteDocument: (filename) => `删除 ${filename}`,
      deleteConfirm: (filename) =>
        `确认删除 ${filename}？其索引证据和上传文件也会被删除。`,
      deleteSuccess: (filename) => `已删除 ${filename}。`,
      deleteFailed: '删除文档失败。',
      quotaBypassed: '评测模式：文档额度已关闭，历史使用记录仍会保留。',
      status: {
        indexed: '已收录',
        processing: '处理中',
        failed: '失败',
        quarantined: '暂不可用，禁止提问',
      },
    },
    upload: {
      title: '上传文档',
      ariaLabel: '上传财务报告',
      idle: '选择文件，或拖到这里',
      uploading: '正在上传...',
      success: '上传完成',
      error: '上传失败，请重试。',
      hint: '支持 PDF、XLSX、DOCX、CSV；单份最大 50 MB，可一次选择多份',
      chooseFile: '选择文件',
      uploadAnother: '继续上传',
      retry: '重试',
      fallbackError: '上传失败。',
      selectedFiles: (count) => `已选择 ${count} 个文件`,
      batchSuccess: (count) => `已成功上传 ${count} 份文档。`,
      batchPartial: (success, failed) => `成功 ${success} 份，失败 ${failed} 份。`,
      duplicateDocument: '当前工作空间已有这份文档。',
      invalidFileType: '支持格式：PDF、XLSX、DOCX、CSV。',
      fileTooLarge: '文件超过 50 MB 上传限制。',
      invalidDocument: '文件无效、已加密或暂不受支持。',
      uploadLimitExceeded: '当前工作空间的上传额度已满。',
      rateLimited: '上传服务当前请求较多，请稍后重试。',
    },
    retrieval: {
      queryFailed: '搜索失败，请重试。',
      queryPlaceholder: '例如：“特斯拉 2025 年营收增长”',
      queryLabel: '搜索内容',
      searching: '正在搜索…',
      search: '搜索',
      queryHint: '查找最多 5 段相关原文。',
      metricsTitle: '搜索信息',
      latency: '搜索耗时',
      chunksRetrieved: '找到片段',
      retrieverType: '搜索方式',
      resultsTitle: '搜索结果',
      resultCount: (count) => `${count} 条结果`,
      page: '页码',
      source: '来源',
      similarity: '匹配度',
      emptyTitle: '内容搜索',
      emptyHint:
        '输入问题，查找相关原文。',
    },
    document: {
      loadFailed: '文档加载失败。',
      loadFailedTitle: '无法加载文档',
      backToDocuments: '返回列表',
      backToKnowledge: '返回文档',
      company: '公司',
      pages: '页数',
      statusLabel: '状态',
      size: '大小',
      uploaded: '上传时间',
      status: {
        indexed: '已收录',
        processing: '处理中',
        failed: '失败',
        quarantined: '暂不可用，禁止提问',
      },
      statistics: '文档信息',
      chunks: '内容片段',
      embeddingStatus: '搜索准备',
      vectorStatus: '搜索存储',
      embedding: {
        completed: '已完成',
        pending: '等待处理',
        failed: '失败',
      },
      vector: {
        stored: '已存储',
        pending: '等待处理',
        failed: '失败',
      },
      chunkExplorer: '浏览内容',
      chunk: (index) => `内容片段 #${index}`,
      noChunks: '暂无内容',
      noChunksHint: '文档未处理完成或内容读取失败。',
    },
    settings: {
      title: '设置',
      subtitle: '管理界面和 AI 服务设置。',
      appearanceTitle: '外观设置',
      appearanceDescription: '调整此设备的显示风格。',
      themeLabel: '显示模式',
      lightTheme: '浅色模式',
      lightThemeDescription: '使用浅色界面。',
      darkTheme: '深色模式',
      darkThemeDescription: '使用深色界面。',
      languageTitle: '语言',
      languageDescription: '选择界面语言。',
      llmTitle: 'AI 服务',
      llmDescription: '设置服务，并选择新问答默认服务。',
      securityNote:
        'API Key 会通过当前连接直接发送到后端，不会存储在浏览器中，也不会在界面完整显示。',
      loading: '正在读取服务设置…',
      loadError: '无法读取 AI 服务设置。',
      retry: '重试',
      noProviders: '暂无可设置的 AI 服务。',
      configured: '已保存',
      notConfigured: '未设置',
      defaultProvider: '默认服务',
      defaultSelectionTitle: '默认服务',
      defaultSelectionDescription: '用于新问答。已保存参数不代表服务正在运行。',
      defaultSelectionLabel: '选择新问答默认服务',
      defaultSelectionValue: (provider, index, total) => `${provider}，第 ${index} 项，共 ${total} 项`,
      defaultSelectionSaving: '正在更新默认服务…',
      defaultSelectionSaved: '新对话默认服务已更新。',
      defaultSelectionFailed: '无法更新默认服务，原选择保持不变。',
      defaultSelectionUseSingle: '将此已配置服务用于新对话',
      keyHint: '密钥已存',
      localEndpointLabel: '服务地址',
      localEndpointPlaceholder: 'http://host.docker.internal:11434',
      localEndpointHelp: 'Docker Desktop 中连接宿主机 Ollama 通常使用 host.docker.internal。仅允许本地 HTTP 地址。',
      localModelLabel: '模型名称',
      localModelPlaceholder: '例如：qwen3.8:latest',
      localModelHelp: '请填写 Ollama 所在机器上 `ollama list` 显示的完整模型标签。',
      apiKeyLabel: '服务密钥',
      apiKeyPlaceholder: '输入新的服务密钥',
      modelLabel: '模型',
      modelPlaceholder: '使用默认模型',
      updatedAt: '更新时间',
      neverUpdated: '尚未更新',
      save: '保存设置',
      saving: '正在保存...',
      saved: '服务设置已保存。',
      clear: '清除设置',
      clearing: '正在清除...',
      confirmClear: '确认清除此 API Key？',
      confirmClearLocal: '确认清除此本地模型配置？',
      confirmClearDescription: '保存新密钥前，使用此服务的请求将无法执行。',
      cancel: '取消',
      cleared: '服务设置已清除。',
      saveError: '无法保存服务设置。',
      clearError: '无法清除服务密钥。',
    },
    errorBoundary: {
      title: '页面出现问题',
      unexpected: '发生了意外错误。',
      returnToChat: '返回问答',
    },
  },
};
