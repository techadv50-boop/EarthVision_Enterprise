import { useEffect, useState } from "react";
import type { Galley, Journal, Store } from "./types";
import { EMPTY_STORE, loadStore, newGalley, saveStore } from "./storage";
import { seedStore } from "./seed";
import { Shelf } from "./ui/Shelf";
import { JournalForm } from "./ui/JournalForm";
import { FirstPage } from "./ui/FirstPage";
import { BodyDesk } from "./ui/BodyDesk";
import { Proof } from "./ui/Proof";

type View =
  | { name: "shelf" }
  | { name: "add" }
  | { name: "edit"; journalId: string }
  | { name: "first"; galleyId: string }
  | { name: "body"; galleyId: string }
  | { name: "proof"; galleyId: string };

export function App() {
  const [store, setStore] = useState<Store>(EMPTY_STORE);
  const [ready, setReady] = useState(false);
  const [view, setView] = useState<View>({ name: "shelf" });
  const [error, setError] = useState("");

  useEffect(() => {
    const existing = loadStore();
    if (existing.journals.length > 0) {
      setStore(existing);
      setReady(true);
      return;
    }
    seedStore()
      .then((seeded) => {
        saveStore(seeded);
        setStore(seeded);
        setReady(true);
      })
      .catch(() => {
        setError("The journal icons could not be loaded. You can still add a journal and upload icons.");
        setReady(true);
      });
  }, []);

  const commit = (next: Store) => {
    setStore(next);
    saveStore(next);
  };

  const galley = view.name === "shelf" || view.name === "add" || view.name === "edit"
    ? undefined
    : store.galleys.find((item) => item.id === view.galleyId);
  const journal = galley ? store.journals.find((item) => item.id === galley.journalId) : undefined;

  const saveGalley = (nextGalley: Galley) => {
    commit({
      ...store,
      galleys: store.galleys.some((item) => item.id === nextGalley.id)
        ? store.galleys.map((item) => (item.id === nextGalley.id ? nextGalley : item))
        : [...store.galleys, nextGalley],
    });
  };

  if (!ready) return <p className="panel">Opening the journal shelf…</p>;

  if (view.name === "add" || view.name === "edit") {
    const initial = view.name === "edit" ? store.journals.find((item) => item.id === view.journalId) : undefined;
    return (
      <JournalForm
        initial={initial}
        onCancel={() => setView({ name: "shelf" })}
        onSave={(saved) => {
          const journals = store.journals.some((item) => item.id === saved.id)
            ? store.journals.map((item) => (item.id === saved.id ? saved : item))
            : [...store.journals, saved];
          commit({ ...store, journals });
          setView({ name: "shelf" });
        }}
      />
    );
  }

  if ((view.name === "first" || view.name === "body" || view.name === "proof") && galley && journal) {
    if (view.name === "first") {
      return (
        <FirstPage
          galley={galley}
          journal={journal}
          openAccess={store.openAccessIcon}
          onChange={saveGalley}
          onBack={() => setView({ name: "shelf" })}
          onNext={() => setView({ name: "body", galleyId: galley.id })}
        />
      );
    }
    if (view.name === "body") {
      return (
        <BodyDesk
          galley={galley}
          journal={journal}
          openAccess={store.openAccessIcon}
          onChange={saveGalley}
          onBack={() => setView({ name: "first", galleyId: galley.id })}
          onProof={() => setView({ name: "proof", galleyId: galley.id })}
        />
      );
    }
    return (
      <Proof
        galley={galley}
        journal={journal}
        openAccess={store.openAccessIcon}
        onBack={() => setView({ name: "body", galleyId: galley.id })}
      />
    );
  }

  return (
    <>
      {error && <p className="error panel">{error}</p>}
      <Shelf
        journals={store.journals}
        galleys={store.galleys}
        onAdd={() => setView({ name: "add" })}
        onEdit={(item: Journal) => setView({ name: "edit", journalId: item.id })}
        onOpenJournal={(item) => {
          const created = newGalley(item);
          commit({ ...store, galleys: [...store.galleys, created] });
          setView({ name: "first", galleyId: created.id });
        }}
        onOpenGalley={(item) => setView({ name: "first", galleyId: item.id })}
        onDeleteGalley={(item) => commit({ ...store, galleys: store.galleys.filter((galley) => galley.id !== item.id) })}
      />
    </>
  );
}
