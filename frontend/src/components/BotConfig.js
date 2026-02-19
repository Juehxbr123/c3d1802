import React, { useEffect, useState } from 'react';
import { Alert, Button, Card, Divider, Form, Input, Tabs, message } from 'antd';
import { ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import axios from 'axios';

const { TextArea } = Input;

const BotConfig = () => {
  const [loading, setLoading] = useState(false);
  const [textsForm] = Form.useForm();
  const [settingsForm] = Form.useForm();

  const loadConfig = React.useCallback(async () => {
    setLoading(true);
    try {
      const [textsResponse, settingsResponse] = await Promise.all([
        axios.get('/api/bot-config/texts'),
        axios.get('/api/bot-config/settings')
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
    } catch {
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
    } catch {
      message.error('Не удалось сохранить настройки');
    } finally {
      setLoading(false);
    }
  };

  const tabs = [
    {
      key: 'texts',
      label: '🧩 Тексты и раздел «О нас»',
      children: (
        <Card title='Конструктор контента'>
          <Form form={textsForm} layout='vertical' onFinish={saveTexts}>
            <Form.Item label='Текст главного меню' name='welcome_menu_msg'>
              <TextArea rows={3} />
            </Form.Item>
            <Form.Item label='Кратко «О нас»' name='about_text'>
              <TextArea rows={3} />
            </Form.Item>
            <Divider>Подразделы «О нас»</Divider>
            <Form.Item label='🏭 Оборудование (caption)' name='about_equipment_text'><TextArea rows={3} /></Form.Item>
            <Form.Item label='🖼 Наши проекты (caption)' name='about_projects_text'><TextArea rows={3} /></Form.Item>
            <Form.Item label='📞 Контакты (caption)' name='about_contacts_text'><TextArea rows={3} /></Form.Item>
            <Form.Item label='📍 На карте (caption)' name='about_map_text'><TextArea rows={3} /></Form.Item>
            <Button type='primary' icon={<SaveOutlined />} htmlType='submit' loading={loading}>Сохранить тексты</Button>
          </Form>
        </Card>
      )
    },
    {
      key: 'settings',
      label: '⚙️ Система и фото',
      children: (
        <Card title='Системные настройки'>
          <Alert
            type='info'
            showIcon
            style={{ marginBottom: 16 }}
            message='Фото можно задавать как путь к файлу внутри контейнера, URL картинки или Telegram file_id. Если поле пустое — используется PLACEHOLDER_PHOTO_PATH.'
          />
          <Form form={settingsForm} layout='vertical' onFinish={saveSettings}>
            <Form.Item label='ID чата/группы для заявок (orders_chat_id)' name='orders_chat_id'>
              <Input placeholder='Например: 5288005751' />
            </Form.Item>
            <Form.Item label='Юзернейм менеджера (manager_username)' name='manager_username'>
              <Input placeholder='например: chel3d_manager' />
            </Form.Item>
            <Form.Item label='Плейсхолдер по умолчанию (placeholder_photo_path)' name='placeholder_photo_path'>
              <Input placeholder='например: /app/assets/placeholder.png или https://...' />
            </Form.Item>
            <Divider>Фото шагов/разделов</Divider>
            <Form.Item label='Главное меню (photo_main_menu)' name='photo_main_menu'><Input /></Form.Item>
            <Form.Item label='Рассчитать печать (photo_print)' name='photo_print'><Input /></Form.Item>
            <Form.Item label='3D-сканирование (photo_scan)' name='photo_scan'><Input /></Form.Item>
            <Form.Item label='Нет модели / идея (photo_idea)' name='photo_idea'><Input /></Form.Item>
            <Form.Item label='О нас (photo_about)' name='photo_about'><Input /></Form.Item>
            <Form.Item label='Оборудование (photo_about_equipment)' name='photo_about_equipment'><Input /></Form.Item>
            <Form.Item label='Наши проекты (photo_about_projects)' name='photo_about_projects'><Input /></Form.Item>
            <Form.Item label='Контакты (photo_about_contacts)' name='photo_about_contacts'><Input /></Form.Item>
            <Form.Item label='На карте (photo_about_map)' name='photo_about_map'><Input /></Form.Item>
            <Button type='primary' icon={<SaveOutlined />} htmlType='submit' loading={loading}>Сохранить настройки</Button>
            <Button style={{ marginLeft: 8 }} icon={<ReloadOutlined />} onClick={loadConfig}>Обновить</Button>
          </Form>
        </Card>
      )
    }
  ];

  return <Tabs items={tabs} />;
};

export default BotConfig;
