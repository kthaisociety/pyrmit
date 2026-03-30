function requireEnv(name: 'NEXT_PUBLIC_API_URL'): string {
  const value = process.env[name]?.trim();
  if (value) {
    return value;
  }

  if (process.env.NODE_ENV === 'production') {
    throw new Error(`${name} must be set for production builds.`);
  }

  return 'http://localhost:8000';
}

export const API_URL = requireEnv('NEXT_PUBLIC_API_URL');
