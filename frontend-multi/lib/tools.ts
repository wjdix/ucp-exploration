import { tool } from 'ai';
import { z } from 'zod';
import {
  generateCheckoutMandate,
  createIntentMandate,
  bindIntentMandate,
} from './ap2';

const CP_URL = process.env.CREDENTIAL_PROVIDER_URL || 'http://localhost:8002';

// Map store IDs to their direct REST URLs (for session fetching during mandate generation)
const STORE_URLS: Record<string, string> = {
  electronics: process.env.BUSINESS_URL || 'http://localhost:8001',
  books: process.env.BUSINESS_2_URL || 'http://localhost:8004',
};

export const getPaymentToken = tool({
  description: 'Get a payment token from the Credential Provider. Call this after the user confirms they want to pay, before completing checkout.',
  inputSchema: z.object({
    amount: z.number().describe('The total amount to charge'),
    currency: z.string().default('USD'),
    merchantName: z.string().describe('The name of the store being purchased from'),
  }),
  execute: async ({ amount, currency, merchantName }) => {
    const res = await fetch(`${CP_URL}/tokens`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: 'user_demo',
        amount,
        currency,
        merchant_name: merchantName,
      }),
    });
    return await res.json();
  },
});

/**
 * AP2 Cart Mandate for multi-store — needs store_id to fetch session from correct store.
 */
export const generateCheckoutMandateTool = tool({
  description:
    'Generate an AP2 checkout mandate for a checkout session. Call this AFTER getting a payment token and BEFORE completing checkout. The mandate cryptographically proves the user approved this specific purchase.',
  inputSchema: z.object({
    storeId: z.string().describe('The store ID (e.g. "electronics" or "books")'),
    sessionId: z.string().describe('The checkout session ID'),
  }),
  execute: async ({ storeId, sessionId }) => {
    const baseUrl = STORE_URLS[storeId];
    if (!baseUrl) {
      return { error: `Unknown store: ${storeId}` };
    }

    const sessionRes = await fetch(`${baseUrl}/checkout-sessions/${sessionId}`);
    if (!sessionRes.ok) {
      return { error: `Failed to fetch session: ${sessionRes.status}` };
    }
    const session = await sessionRes.json();

    if (!session.ap2?.merchant_authorization) {
      return { error: 'Session missing merchant authorization' };
    }

    const mandate = await generateCheckoutMandate(session);
    return { checkout_mandate: mandate };
  },
});

/**
 * Intent Mandate creation — factory that captures conversation history.
 */
export function createIntentMandateToolWithMessages(
  messages: Array<{ role: string; content: string }>,
) {
  return tool({
    description:
      'Create an AP2 intent mandate for autonomous purchases. Use when the user wants to authorize future purchases without per-transaction approval.',
    inputSchema: z.object({
      maxAmountCents: z.number().describe('Maximum amount per transaction in cents'),
      maxTotalCents: z.number().describe('Maximum total spend in cents across all uses'),
      currency: z.string().default('USD'),
      merchantIds: z.array(z.string()).describe('List of merchant/store IDs authorized (e.g. ["electronics", "books"])'),
      maxUses: z.number().describe('Maximum number of transactions allowed'),
      expiresInHours: z.number().describe('Hours until mandate expires'),
      summary: z.string().describe('A concise human-readable summary of what is being authorized'),
    }),
    execute: async ({
      maxAmountCents,
      maxTotalCents,
      currency,
      merchantIds,
      maxUses,
      expiresInHours,
      summary,
    }) => {
      const turns = messages.map((m) => ({
        role: m.role,
        content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
      }));

      return await createIntentMandate({
        maxAmount: maxAmountCents,
        maxTotal: maxTotalCents,
        currency,
        merchantIds,
        maxUses,
        expiresInHours,
        conversation: {
          model: 'claude-sonnet-4-20250514',
          turns,
          turnCount: turns.length,
        },
        summary,
      });
    },
  });
}

/**
 * Bind an intent mandate for autonomous completion.
 */
export const bindAndCompleteWithIntentTool = tool({
  description:
    'Bind an intent mandate to a checkout session for autonomous completion.',
  inputSchema: z.object({
    mandateId: z.string().describe('The intent mandate ID'),
    sessionId: z.string().describe('The checkout session ID'),
    amountCents: z.number().describe('Transaction amount in cents'),
  }),
  execute: async ({ mandateId, sessionId, amountCents }) => {
    const result = await bindIntentMandate(mandateId, sessionId, amountCents);
    if ('error' in result) {
      return { error: result.error };
    }
    return { intent_mandate: result.mandate };
  },
});
