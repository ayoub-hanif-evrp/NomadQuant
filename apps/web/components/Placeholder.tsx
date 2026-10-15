export function Placeholder({
  title,
  note,
}: {
  title: string;
  note: string;
}) {
  return (
    <section className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-6 text-lg font-medium">Not implemented yet</p>
      <p className="mt-3 max-w-xl text-sm leading-6 text-[#93a1b5]">{note}</p>
    </section>
  );
}
