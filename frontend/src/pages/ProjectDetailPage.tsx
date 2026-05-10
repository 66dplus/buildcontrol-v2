import { useParams } from "react-router-dom";

export function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div>
      <h1 className="font-heading text-2xl mb-2">Проект #{id}</h1>
      <p className="text-muted text-sm">Slice 3 — табы, бюджет, материалы.</p>
    </div>
  );
}
