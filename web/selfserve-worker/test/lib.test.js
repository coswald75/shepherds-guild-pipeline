import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  maxUploadBytes,
  looksLikeAudio,
  validateFields,
  selfServeKey,
  presignS3,
  signTicket,
  verifyTicket,
} from "../src/lib.js";

describe("validateFields", () => {
  const base = {
    name: "Jane Doe",
    email: "jane@church.org",
    filename: "sermon.mp3",
    type: "audio/mpeg",
    size: 40_000_000,
    maxBytes: maxUploadBytes("200"),
  };

  it("accepts a normal sermon MP3", () => {
    assert.equal(validateFields(base), null);
  });

  it("accepts an empty type when the name ends in .mp3", () => {
    assert.equal(validateFields({ ...base, type: "" }), null);
  });

  it("rejects over 200 MB with ordinary wording", () => {
    const err = validateFields({ ...base, size: 200_000_001 });
    assert.match(err, /too large/);
    assert.match(err, /200 MB/);
  });

  it("accepts a 101–150 MB file under the 200 MB cap", () => {
    assert.equal(validateFields({ ...base, size: 101_000_000 }), null);
    assert.equal(validateFields({ ...base, size: 150_000_000 }), null);
  });

  it("rejects a missing name and a bad email", () => {
    assert.match(validateFields({ ...base, name: "" }), /name/i);
    assert.match(validateFields({ ...base, email: "not-an-email" }), /email/i);
  });

  it("rejects a non-audio file", () => {
    assert.match(
      validateFields({ ...base, filename: "notes.pdf", type: "application/pdf" }),
      /MP3/,
    );
  });
});

describe("looksLikeAudio / selfServeKey", () => {
  it("treats audio/* or .mp3 as audio", () => {
    assert.equal(looksLikeAudio("talk.mp3", ""), true);
    assert.equal(looksLikeAudio("talk.wav", "audio/wav"), true);
    assert.equal(looksLikeAudio("talk.txt", "text/plain"), false);
  });

  it("keeps the poller R2 key shape", () => {
    const id = "11111111-1111-4111-8111-111111111111";
    assert.equal(selfServeKey(id), `self-serve/${id}.mp3`);
  });
});

describe("presignS3 (AWS published GET vector)", () => {
  // https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
  it("matches the official query-string signature", async () => {
    const url = await presignS3({
      accessKeyId: "AKIAIOSFODNN7EXAMPLE",
      secretAccessKey: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
      region: "us-east-1",
      method: "GET",
      host: "examplebucket.s3.amazonaws.com",
      canonicalUri: "/test.txt",
      expiresSec: 86400,
      amzDate: "20130524T000000Z",
    });
    const u = new URL(url);
    assert.equal(u.host, "examplebucket.s3.amazonaws.com");
    assert.equal(u.pathname, "/test.txt");
    assert.equal(u.searchParams.get("X-Amz-Algorithm"), "AWS4-HMAC-SHA256");
    assert.equal(
      u.searchParams.get("X-Amz-Signature"),
      "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404",
    );
  });
});

describe("tickets", () => {
  const secret = "test-ticket-secret";
  const payload = {
    v: 1,
    id: "22222222-2222-4222-8222-222222222222",
    name: "Jane",
    church: "Grace",
    email: "jane@church.org",
    key: "self-serve/22222222-2222-4222-8222-222222222222.mp3",
    exp: Date.now() + 60_000,
  };

  it("round-trips a valid ticket", async () => {
    const ticket = await signTicket(secret, payload);
    const got = await verifyTicket(secret, ticket);
    assert.equal(got.id, payload.id);
    assert.equal(got.email, payload.email);
    assert.equal(got.key, payload.key);
  });

  it("rejects a tampered ticket, the wrong secret, and an expired ticket", async () => {
    const ticket = await signTicket(secret, payload);
    assert.equal(await verifyTicket(secret, ticket + "x"), null);
    assert.equal(await verifyTicket("other", ticket), null);
    const expired = await signTicket(secret, { ...payload, exp: Date.now() - 1 });
    assert.equal(await verifyTicket(secret, expired), null);
  });
});
