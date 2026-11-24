'use client';

import { Store } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';

// Bağlantı ekranının işlevi bu sürümün kapsamı dışındadır; diyalog yalnız ne olacağını anlatır.
export function ConnectStoreDialog() {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button>
          <Store aria-hidden="true" />
          Trendyol mağazasını bağla
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Trendyol bağlantısı yakında</DialogTitle>
          <DialogDescription>
            Bağlantı adımı bir sonraki sürümde açılacak. Trendyol panelinden alacağınız API
            bilgilerini yapıştırmanız yeterli olacak. Bağlantı yalnız okuma yapar ve istediğiniz an
            kesebilirsiniz.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="secondary">Tamam</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
