import { Button, Stack, Text, Textarea, TextInput } from '@mantine/core'
import { type FormEvent, useState } from 'react'

import { type Booking, type BookingInput, createBooking } from './api'

export interface GuestDetails {
  guestName: string
  guestEmail: string
  guestTopic: string
}

type GuestFieldErrors = Partial<Record<keyof GuestDetails, string>>

const emailAtom = "[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
const domainLabel = '[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
const emailPattern = new RegExp(
  `^${emailAtom}(?:\\.${emailAtom})*@${domainLabel}(?:\\.${domainLabel})*$`,
)

interface BookingFormProps {
  typeId: string
  startsAt: string
  onConfirmed: (booking: Booking) => void
  contact: GuestDetails
  onContactChange: (contact: GuestDetails) => void
  onBack: (notice?: string) => void
}

export function BookingForm({
  typeId,
  startsAt,
  contact,
  onContactChange,
  onConfirmed,
  onBack,
}: BookingFormProps) {
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState<GuestFieldErrors>({})
  const [failed, setFailed] = useState(false)

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (saving) return
    const guestName = contact.guestName.trim()
    const guestEmail = contact.guestEmail.trim()
    const guestTopic = contact.guestTopic.trim()
    const nextErrors: typeof errors = {}
    if (!guestName || [...guestName].length > 100)
      nextErrors.guestName = 'Введите имя длиной от 1 до 100 символов'
    if ([...guestEmail].length > 254 || !emailPattern.test(guestEmail))
      nextErrors.guestEmail = 'Введите корректный email длиной до 254 символов'
    if ([...guestTopic].length > 1000)
      nextErrors.guestTopic = 'Тема разговора должна содержать до 1000 символов'
    setErrors(nextErrors)
    setFailed(false)
    if (Object.keys(nextErrors).length > 0) return
    setSaving(true)
    const body: BookingInput = {
      meetingTypeId: typeId,
      startsAt,
      guestName,
      guestEmail,
      ...(guestTopic ? { guestTopic } : {}),
    }
    const { data, error, response } = await createBooking({ body })
    setSaving(false)
    if (response?.status === 201 && data) {
      onConfirmed(data)
    } else if (response?.status === 409 && error?.code === 'SLOT_TAKEN') {
      onBack('Это время уже занято. Выберите другой слот')
    } else if (response?.status === 400 && error?.code === 'INVALID_START') {
      onBack('Это время уже недоступно')
    } else if (
      response?.status === 400 &&
      error?.code === 'INVALID_INPUT' &&
      (error.field === 'guestName' ||
        error.field === 'guestEmail' ||
        error.field === 'guestTopic') &&
      typeof error.message === 'string' &&
      error.message.trim()
    ) {
      setErrors({ [error.field]: error.message })
    } else {
      setFailed(true)
    }
  }

  return (
    <form noValidate onSubmit={confirm}>
      <Stack>
        <TextInput
          label="Имя"
          placeholder="Как вас зовут?"
          name="guestName"
          value={contact.guestName}
          disabled={saving}
          onChange={(event) =>
            onContactChange({ ...contact, guestName: event.currentTarget.value })
          }
          autoComplete="name"
          error={errors.guestName}
          required
        />
        <TextInput
          label="Email"
          placeholder="name@example.org"
          name="guestEmail"
          value={contact.guestEmail}
          disabled={saving}
          onChange={(event) =>
            onContactChange({ ...contact, guestEmail: event.currentTarget.value })
          }
          type="email"
          autoComplete="email"
          error={errors.guestEmail}
          required
        />
        <Textarea
          label="Тема разговора"
          description="Список предстоящих событий открыт всем"
          placeholder="О чём хотите поговорить?"
          name="guestTopic"
          value={contact.guestTopic}
          disabled={saving}
          onChange={(event) =>
            onContactChange({ ...contact, guestTopic: event.currentTarget.value })
          }
          error={errors.guestTopic}
        />
        {failed && <Text role="alert">Не удалось подтвердить запись</Text>}
        <div className="form-actions">
          <Button type="submit" loading={saving}>
            Подтвердить запись
          </Button>
          <Button type="button" variant="default" disabled={saving} onClick={() => onBack()}>
            Выбрать другое время
          </Button>
        </div>
      </Stack>
    </form>
  )
}
