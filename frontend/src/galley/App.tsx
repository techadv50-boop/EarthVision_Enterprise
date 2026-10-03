import { useEffect, useRef, useState, type ReactNode } from "react";
import { isCitationAdmin, useAuthStore } from "@/store/authStore";
import type { Galley, IconAsset, Journal } from "./types";
import { newGalley, normalizeGalley } from "./storage";
import { seedStore } from "./seed";
import * as api from "./api";
import type { Account, GalleyRecord } from "./api";
import { Shelf } from "./ui/Shelf";
import { JournalForm } from "./ui/JournalForm";
import { FirstPage } from "./ui/FirstPage";
import { BodyDesk } from "./ui/BodyDesk";
import { Proof } from "./ui/Proof";
import { Admin } from "./ui/Admin";
import "./styles.css";

type View =
  | { name: "shelf" }
  | { name: "admin" }
  | { name: "add" }
  | { name: "edit"; journalId: string }
  | { name: "first"; galleyId: string }
  | { name: "body"; galleyId: string }
  | { name: "proof"; galleyId: string };

function accountFromAuth(): Account | null {
  const user = useAuthStore.getState().user;
  if (!user) return null;
  return {
    id: String(user.id),
    name: user.full_name || user.username,
    email: user.email,
    role: isCitationAdmin(user) ? "admin" : "user",
    status: "approved",
  };
}

export function GalleyDesk() {
  const authUser = useAuthStore((s) => s.user);
  const [user, setUser] = useState<Account | null>(accountFromAuth);
  const [loading, setLoading] = useState(true);
  const [journals, setJournals] = useState<Journal[]>([]);
  const [openAccess, setOpenAccess] = useState<IconAsset | null>(null);
  const [archive, setArchive] = useState<GalleyRecord[]>([]);
  const [view, setView] = useState<View>({ name: "shelf" });
  const [error, setError] = useState("");
  const saves = useRef(new Map<string, number>());
  const pending = useRef(new Map<string, Galley>());

  useEffect(() => {
    setUser(accountFromAuth());
  }, [authUser]);

  useEffect(() => {
    if (!user) return;
    let cancel = false;
    setLoading(true);
    (async () => {
      const [loaded, records, settings] = await Promise.all([api.journals(), api.galleys(), api.openAccess()]);
      let nextJournals = loaded;
      let icon = settings.icon;
      if (user.role === "admin" && loaded.length === 0) {
        try {
          const seeded = await seedStore();
          for (const journal of seeded.journals) await api.saveJournal(journal);
          if (seeded.openAccessIcon) await api.saveOpenAccess(seeded.openAccessIcon);
          nextJournals = seeded.journals;
          icon = seeded.openAccessIcon;
        } catch {
          if (!cancel) setError("The starter journals could not be loaded. Add a journal from Admin.");
        }
      }
      if (cancel) return;
      setJournals(nextJournals);
      setOpenAccess(icon);
      setArchive(records.map((record) => ({ ...record, galley: normalizeGalley(record.galley) })));
    })()
      .catch((caught: unknown) => {
        if (!cancel) setError(caught instanceof Error ? caught.message : "Could not open the desk.");
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [user]);

  const saveGalley = (next: Galley) => {
    setArchive((current) => current.map((record) => (record.galley.id === next.id ? { ...record, galley: next } : record)));
    pending.current.set(next.id, next);
    const waiting = saves.current.get(next.id);
    if (waiting) window.clearTimeout(waiting);
    saves.current.set(
      next.id,
      window.setTimeout(() => {
        void flushGalley(next.id);
      }, 400),
    );
  };

  const flushGalley = (id: string) => {
    const waiting = saves.current.get(id);
    if (waiting) window.clearTimeout(waiting);
    saves.current.delete(id);
    const latest = pending.current.get(id);
    pending.current.delete(id);
    if (!latest) return Promise.resolve();
    return api.updateGalley(latest).catch((caught: unknown) => {
      setError(caught instanceof Error ? caught.message : "Could not save the galley.");
    });
  };

  if (!user || loading) {
    return (
      <div className="galley-root">
        <p className="panel">Opening the journal shelf…</p>
      </div>
    );
  }

  const record = "galleyId" in view ? archive.find((item) => item.galley.id === view.galleyId) : undefined;
  const galley = record?.galley;
  const journal = galley ? journals.find((item) => item.id === galley.journalId) : undefined;

  const wrap = (node: ReactNode) => (
    <div className="galley-root">
      {error && <p className="error panel">{error}</p>}
      {node}
    </div>
  );

  if (view.name === "add" || view.name === "edit") {
    if (user.role !== "admin") return wrap(<p className="panel">Only an admin can change journals.</p>);
    const initial = view.name === "edit" ? journals.find((item) => item.id === view.journalId) : undefined;
    return wrap(
      <JournalForm
        initial={initial}
        onCancel={() => setView({ name: "admin" })}
        onSave={(saved) => {
          api
            .saveJournal(saved)
            .then((stored) => {
              setJournals((current) =>
                current.some((item) => item.id === stored.id)
                  ? current.map((item) => (item.id === stored.id ? stored : item))
                  : [...current, stored],
              );
              setView({ name: "admin" });
            })
            .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Could not save the journal."));
        }}
      />,
    );
  }

  if (view.name === "admin") {
    if (user.role !== "admin") return wrap(<p className="panel">Only an admin can open that page.</p>);
    return wrap(
      <Admin
        journals={journals}
        archive={archive}
        onBack={() => setView({ name: "shelf" })}
        onAddJournal={() => setView({ name: "add" })}
        onEditJournal={(item) => setView({ name: "edit", journalId: item.id })}
        onOpenGalley={(item) => setView({ name: "first", galleyId: item.galley.id })}
        onDeleteJournal={(item) => {
          if (!window.confirm(`Delete ${item.abbreviation}? Composers will no longer see this journal.`)) return;
          api
            .deleteJournal(item.id)
            .then(() => setJournals((current) => current.filter((journalItem) => journalItem.id !== item.id)))
            .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Could not delete the journal."));
        }}
        onDeleteGalley={(item) => {
          if (!window.confirm("Delete this galley from the archive?")) return;
          api
            .deleteGalley(item.galley.id)
            .then(() => {
              setArchive((current) => current.filter((recordItem) => recordItem.galley.id !== item.galley.id));
              setView({ name: "admin" });
            })
            .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Could not delete the galley."));
        }}
      />,
    );
  }

  if ((view.name === "first" || view.name === "body" || view.name === "proof") && galley && journal) {
    if (view.name === "first") {
      return wrap(
        <FirstPage
          galley={galley}
          journal={journal}
          openAccess={openAccess}
          onChange={saveGalley}
          onBack={() => {
            void flushGalley(galley.id);
            setView({ name: "shelf" });
          }}
          onNext={() => {
            void flushGalley(galley.id);
            setView({ name: "body", galleyId: galley.id });
          }}
        />,
      );
    }
    if (view.name === "body") {
      return wrap(
        <BodyDesk
          galley={galley}
          journal={journal}
          openAccess={openAccess}
          onChange={saveGalley}
          onBack={() => {
            void flushGalley(galley.id);
            setView({ name: "first", galleyId: galley.id });
          }}
          onProof={() => {
            void flushGalley(galley.id);
            setView({ name: "proof", galleyId: galley.id });
          }}
        />,
      );
    }
    return wrap(
      <Proof galley={galley} journal={journal} openAccess={openAccess} onBack={() => setView({ name: "body", galleyId: galley.id })} />,
    );
  }

  const mine = archive.filter((item) => item.ownerId === user.id).map((item) => item.galley);

  return wrap(
    <Shelf
      journals={journals}
      galleys={mine}
      accountName={user.name}
      isAdmin={user.role === "admin"}
      onAdmin={() => setView({ name: "admin" })}
      onOpenJournal={(item) => {
        const created = newGalley(item);
        api
          .createGalley(created)
          .then((stored) => {
            const galleyRecord: GalleyRecord = {
              galley: normalizeGalley(stored),
              ownerId: user.id,
              ownerName: user.name,
              ownerEmail: user.email,
            };
            setArchive((current) => [galleyRecord, ...current]);
            setView({ name: "first", galleyId: stored.id });
          })
          .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Could not start that galley."));
      }}
      onOpenGalley={(item) => setView({ name: "first", galleyId: item.id })}
    />,
  );
}

export default GalleyDesk;
