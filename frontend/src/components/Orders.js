import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Divider, Form, Input, Switch, Tabs, message } from 'antd';
import { ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import axios from 'axios';

const { TextArea } = Input;

const textFields = {
  general: [
    ['welcome_menu_msg', 'Текст главного меню'],
    ['text_result_prefix', 'Префикс итога заявки'],
    ['text_price_note', 'Строка про стоимость'],
    ['text_submit_ok', 'Сообщение после успешной отправки'],
    ['text_submit_fail', 'Сообщение при ошибке отправки'],
  ],
  menu: [
    ['btn_menu_print', 'Кнопка главного меню: печать'],
    ['btn_menu_scan', 'Кнопка главного меню: сканирование'],
    ['btn_menu_idea', 'Кнопка главного меню: идея'],
    ['btn_menu_about', 'Кнопка главного меню: о нас'],
  ],
  print: [
    ['text_print_tech', 'Описание шага выбора технологии'],
    ['btn_print_fdm', 'Кнопка технологии: FDM'],
    ['btn_print_resin', 'Кнопка технологии: фотополимер'],
    ['btn_print_unknown', 'Кнопка технологии: не знаю'],
    ['text_select_material', 'Описание шага выбора материала'],
    ['text_describe_material', 'Описание шага «свой материал»'],
    ['text_attach_file', 'Описание шага вложения'],
  ],
  scan: [
    ['text_scan_type', 'Описание шага сканирования'],
    ['btn_scan_human', 'Кнопка скан: человек'],
    ['btn_scan_object', 'Кнопка скан: предмет'],
    ['btn_scan_industrial', 'Кнопка скан: промышленный объект'],
    ['btn_scan_other', 'Кнопка скан: другое'],
  ],
  idea: [
    ['text_idea_type', 'Описание шага идеи'],
    ['btn_idea_photo', 'Кнопка идея: по фото/эскизу'],
    ['btn_idea_award', 'Кнопка идея: сувенир/кубок/медаль'],
    ['btn_idea_master', 'Кнопка идея: мастер-модель'],
    ['btn_idea_sign', 'Кнопка идея: вывески'],
    ['btn_idea_other', 'Кнопка идея: другое'],
    ['text_describe_task', 'Описание шага свободного ввода'],
  ],
  about: [
    ['about_text', 'Описание раздела «О нас»'],
    ['btn_about_equipment', 'Кнопка «Оборудование»'],
    ['btn_about_projects', 'Кнопка «Наши проекты»'],
    ['btn_about_contacts', 'Кнопка «Контакты»'],
    ['btn_about_map', 'Кнопка «На карте»'],
    ['about_equipment_text', 'Текст «Оборудование»'],
    ['about_projects_text', 'Текст «Наши проекты»'],
    ['about_contacts_text', 'Текст «Контакты»'],
    ['about_map_text', 'Текст «На карте»'],
  ],
};

const toggleFields = [
  ['enabled_menu_print', 'Показывать кнопку меню: печать'],
  ['enabled_menu_scan', 'Показывать кнопку меню: сканирование'],
  ['enabled_menu_idea', 'Показывать кнопку меню: идея'],
  ['enabled_menu_about', 'Показывать кнопку меню: о нас'],
];

const photoFields = [
  ['photo_main_menu', 'Фото главного меню (file_id / путь / URL)'],
  ['photo_print', 'Фото ветки печати'],
  ['photo_scan', 'Фото ветки сканирования'],
  ['photo_idea', 'Фото ветки идеи'],
  ['photo_about', 'Фото раздела о нас'],
  ['photo_about_equipment', 'Фото раздела оборудование'],
  ['photo_about_projects', 'Фото раздела проекты'],
  ['photo_about_contacts', 'Фото раздела контакты'],
  ['photo_about_map', 'Фото раздела карта'],
];

const systemFields = [
  ['orders_chat_id', 'ID чата «Заказы» (куда бот шлёт заявки)'],
  ['manager_username', 'Юзернейм менеджера (опционально)'],
  ['placeholder_photo_path', 'Фото по умолчанию (file_id / путь / URL)'],
];

export default function BotConfig() {
  const [loading, setLoading] = useState(false);
  const [textsForm] = Form.useForm();
  const [settingsForm] = Form.useForm();

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const [textsResponse, settingsResponse] = await Promise.all([
        axios.get('/api/bot-config/texts'),
        axios.get('/api/bot-config/settings'),
      ]);
      textsForm.setFieldsValue(textsResponse.data || {});
      settingsForm.setFieldsValue(settingsResponse.data || {});
    } catch (error) {
      message.error('Ошибка загрузки настроек');
    } finally {
      setLoading(false);
    }
  }, [settingsForm, textsForm]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const saveTexts = async (values) => {
    setLoading(true);
    try {
      await axios.put('/api/bot-config/texts', values);
      message.success('Тексты сохранены');
    } catch (error) {
      message.error('Не удалось сохранить тексты');
    } finally {
      setLoading(false);
    }
  };

  const saveSettings = async (values) => {
    setLoading(true);
    try {
      await axios.put('/api/bot-config/settings', values);
      message.success('Настройки сохранены');
    } catch (error) {
      message.error('Не удалось сохранить настройки');
    } finally {
      setLoading(false);
    }
  };

  const renderTextSection = (title, fields) => (
    <Card title={title} style={{ marginBottom: 12 }}>
      {fields.map(([name, label]) => (
        <Form.Item key={name} label={label} name={name}>
          <TextArea rows={2} />
        </Form.Item>
      ))}
    </Card>
  );

  const renderSettingsSection = (title, fields, isSwitch = false) => (
    <Card title={title} style={{ marginBottom: 12 }}>
      {fields.map(([name, label]) => (
        <Form.Item key={name} label={label} name={name} valuePropName={isSwitch ? 'checked' : 'value'}>
          {isSwitch ? <Switch /> : <Input />}
        </Form.Item>
      ))}
    </Card>
  );

  const tabs = [
    {
      key: 'texts',
      label: '🧩 Тексты и подписи',
      children: (
        <Form form={textsForm} layout="vertical" onFinish={saveTexts}>
          <Alert
            type="info"
            showIcon
            message="Здесь настраиваются тексты сообщений и подписи кнопок Telegram-бота."
            style={{ marginBottom: 12 }}
          />
          {renderTextSection('Общие', textFields.general)}
          {renderTextSection('Главное меню', textFields.menu)}
          {renderTextSection('Печать', textFields.print)}
          {renderTextSection('Сканирование', textFields.scan)}
          {renderTextSection('Идея / Нет модели', textFields.idea)}
          {renderTextSection('О нас', textFields.about)}

          <Divider />
          <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={loading}>
            Сохранить тексты
          </Button>
        </Form>
      ),
    },
    {
      key: 'settings',
      label: '⚙️ Системные настройки',
      children: (
        <Form form={settingsForm} layout="vertical" onFinish={saveSettings}>
          <Alert
            type="warning"
            showIcon
            message="Настройки маршрутизации заявок и медиа."
            style={{ marginBottom: 12 }}
          />
          {renderSettingsSection('Системные поля', systemFields, false)}
          {renderSettingsSection('Включатели', toggleFields, true)}
          {renderSettingsSection('Фото', photoFields, false)}

          <Divider />
          <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={loading}>
            Сохранить настройки
          </Button>
        </Form>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="Настройки Telegram-бота"
        extra={
          <Button icon={<ReloadOutlined />} onClick={loadConfig} loading={loading}>
            Обновить
          </Button>
        }
      >
        <Tabs items={tabs} />
      </Card>
    </div>
  );
}