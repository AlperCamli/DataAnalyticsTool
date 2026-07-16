/**
 * A scripted TS wire client — the "runner" side of the conformance
 * tests, able to misbehave in ways the real SDK runner never would
 * (stale tokens, staged-invalid deliveries, skipped heartbeats).
 */

export interface WireResponse {
  status: number;
  json: Record<string, unknown>;
}

export class WireClient {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
  ) {}

  async post(path: string, body?: unknown, rawBody?: string): Promise<WireResponse> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${this.token}`,
        "content-type": "application/json",
        "x-cl-protocol-version": "1",
      },
      body: rawBody ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
    const text = await response.text();
    return { status: response.status, json: text ? JSON.parse(text) : {} };
  }

  async get(path: string): Promise<WireResponse> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      headers: { authorization: `Bearer ${this.token}` },
    });
    const text = await response.text();
    return { status: response.status, json: text ? JSON.parse(text) : {} };
  }

  enqueue(request: Record<string, unknown>): Promise<WireResponse> {
    return this.post("/v1/jobs", request);
  }

  claim(body: Record<string, unknown>): Promise<WireResponse> {
    return this.post("/v1/jobs/claim", body);
  }

  start(jobId: string, leaseToken: string): Promise<WireResponse> {
    return this.post(`/v1/jobs/${jobId}/start`, { lease_token: leaseToken });
  }

  heartbeat(
    jobId: string,
    leaseToken: string,
    progress?: Record<string, unknown>,
  ): Promise<WireResponse> {
    return this.post(`/v1/jobs/${jobId}/heartbeat`, { lease_token: leaseToken, progress });
  }

  /** Splices `resultBytes` verbatim into the body, like the SDK runner. */
  completeRaw(jobId: string, leaseToken: string, resultBytes: string): Promise<WireResponse> {
    const raw = `{"lease_token":${JSON.stringify(leaseToken)},"result":${resultBytes.trim()}}`;
    return this.post(`/v1/jobs/${jobId}/complete`, undefined, raw);
  }

  fail(jobId: string, leaseToken: string, error: Record<string, unknown>): Promise<WireResponse> {
    return this.post(`/v1/jobs/${jobId}/fail`, { lease_token: leaseToken, error });
  }

  defer(
    jobId: string,
    leaseToken: string,
    retryAfterS: number,
    reason: Record<string, unknown>,
  ): Promise<WireResponse> {
    return this.post(`/v1/jobs/${jobId}/defer`, {
      lease_token: leaseToken,
      retry_after_s: retryAfterS,
      reason,
    });
  }

  cancel(jobId: string): Promise<WireResponse> {
    return this.post(`/v1/jobs/${jobId}/cancel`);
  }

  job(jobId: string): Promise<WireResponse> {
    return this.get(`/v1/jobs/${jobId}`);
  }

  async waitForState(
    jobId: string,
    states: string[],
    timeoutMs = 30_000,
  ): Promise<Record<string, unknown>> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const { status, json } = await this.job(jobId);
      if (status === 200 && states.includes(json.state as string)) return json;
      if (Date.now() > deadline) {
        throw new Error(
          `job ${jobId} did not reach ${states.join("|")} within ${timeoutMs}ms ` +
            `(last: ${JSON.stringify(json.state)})`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
}

export const DEMO_DECLARATION = [
  { name: "static-demo", version: "0.1.0", types: ["snapshot"] },
];
