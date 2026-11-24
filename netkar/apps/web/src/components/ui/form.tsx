'use client';

import { Slot } from '@radix-ui/react-slot';
import * as React from 'react';
import {
  Controller,
  FormProvider,
  useFormContext,
  useFormState,
  type ControllerProps,
  type FieldPath,
  type FieldValues,
} from 'react-hook-form';

import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

// shadcn/ui "Form" kalıbı: etiket, açıklama ve hata mesajı alanla aria ilişkileriyle bağlanır.
const Form = FormProvider;

interface FormFieldContextValue {
  name: string;
}
const FormFieldContext = React.createContext<FormFieldContextValue | null>(null);

interface FormItemContextValue {
  id: string;
}
const FormItemContext = React.createContext<FormItemContextValue | null>(null);

const FormField = <
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
>(
  props: ControllerProps<TFieldValues, TName>,
) => (
  <FormFieldContext.Provider value={{ name: props.name }}>
    <Controller {...props} />
  </FormFieldContext.Provider>
);

function useFormField() {
  const fieldContext = React.useContext(FormFieldContext);
  const itemContext = React.useContext(FormItemContext);
  const { getFieldState, control } = useFormContext();
  if (!fieldContext || !itemContext) {
    throw new Error('useFormField, FormField ve FormItem içinde kullanılmalı.');
  }
  const formState = useFormState({ control, name: fieldContext.name });
  const fieldState = getFieldState(fieldContext.name, formState);
  const { id } = itemContext;
  return {
    id,
    name: fieldContext.name,
    formItemId: `${id}-item`,
    formDescriptionId: `${id}-description`,
    formMessageId: `${id}-message`,
    ...fieldState,
  };
}

function FormItem({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  const id = React.useId();
  return (
    <FormItemContext.Provider value={{ id }}>
      <div className={cn('flex flex-col gap-2', className)} {...props} />
    </FormItemContext.Provider>
  );
}

function FormLabel({ className, ...props }: React.ComponentProps<typeof Label>) {
  const { formItemId } = useFormField();
  return <Label className={className} htmlFor={formItemId} {...props} />;
}

function FormControl(props: React.ComponentProps<typeof Slot>) {
  const { error, formItemId, formDescriptionId, formMessageId } = useFormField();
  return (
    <Slot
      id={formItemId}
      aria-describedby={error ? `${formDescriptionId} ${formMessageId}` : formDescriptionId}
      aria-invalid={error ? true : undefined}
      {...props}
    />
  );
}

function FormDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  const { formDescriptionId } = useFormField();
  return (
    <p
      id={formDescriptionId}
      className={cn('text-sm text-muted-foreground', className)}
      {...props}
    />
  );
}

// Hata mesajı ikonla ve "Hata:" ön ekiyle verilir; yalnız kırmızı renge dayanmaz.
function FormMessage({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  const { error, formMessageId } = useFormField();
  const body = error ? String(error.message ?? '') : children;
  if (!body) return null;
  return (
    <p
      id={formMessageId}
      role="alert"
      className={cn('flex items-start gap-1.5 text-sm font-medium text-loss', className)}
      {...props}
    >
      <span aria-hidden="true" className="mt-0.5 font-bold">
        !
      </span>
      <span>
        <span className="sr-only">Hata: </span>
        {body}
      </span>
    </p>
  );
}

export {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  useFormField,
};
