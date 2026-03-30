import DevAccessForm from './dev-access-form';

type SearchParams = Record<string, string | string[] | undefined>;

type DevAccessPageProps = {
  searchParams?: Promise<SearchParams>;
};

function getNextPath(rawValue: string | string[] | undefined): string {
  const value = Array.isArray(rawValue) ? rawValue[0] : rawValue;
  return value?.startsWith('/') ? value : '/';
}

export default async function DevAccessPage({
  searchParams,
}: DevAccessPageProps) {
  const resolvedSearchParams = searchParams ? await searchParams : undefined;
  const nextPath = getNextPath(resolvedSearchParams?.next);

  return <DevAccessForm nextPath={nextPath} />;
}
