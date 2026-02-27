import { getPlatformJwks } from '@/lib/ap2';

export async function GET() {
  const jwks = await getPlatformJwks();
  return Response.json(jwks, {
    headers: { 'Cache-Control': 'public, max-age=3600' },
  });
}
