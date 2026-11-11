export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** parsed JSON error body, when the server sent one (e.g. per-cell problems) */
    public body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
