export type Attempt = {
  n: number;
  text: string;
  words: number;
  durationSeconds: number;
  targetSeconds: number;
  fits: boolean;
  speed: number;
};

export type Description = {
  gapId: string;
  text: string;
  startsAt: number;
  durationSeconds: number;
  availableSeconds: number;
  attemptCount: number;
  firstPass: boolean;
  attempts: Attempt[];
};

export type Gap = {
  gapId: string;
  start: number;
  end: number;
  duration: number;
  kind: string;
  narrated: boolean;
};

export type Project = {
  projectId: string;
  videoId: string;
  durationSeconds: number | null;
  videoUrl: string;
  originalUrl: string;
  downloadUrl: string;
  audioUrl: string;
  vttUrl: string;
  gaps: Gap[];
  coverage: {
    before: number;
    after: number;
    checker: string | null;
    facts: { text: string; recovered: boolean }[];
  };
  metrics: {
    gapsFound: number;
    gapSeconds: number;
    toFill: number;
    toSkip: number;
    density: number;
    firstPassFitRate: number;
    finalFitRate: number;
    totalAttempts: number;
    overruns: number;
  };
  descriptions: Description[];
  provenance: {
    manifestKey: string | null;
    bucket: string | null;
    canonicalHash: string | null;
    steps: number | null;
    retainUntil: string | null;
    lockMode: string;
  };
};
