import { sendWhatsApp } from '../src/index'
import axios from 'axios'

jest.mock('axios')
const mockedAxios = axios as jest.Mocked<typeof axios>

describe('sendWhatsApp', () => {
  beforeEach(() => {
    process.env.MOCK_WHATSAPP = 'true'
    jest.clearAllMocks()
  })

  test('should mock send WhatsApp', async () => {
    const consoleSpy = jest.spyOn(console, 'log').mockImplementation()
    await sendWhatsApp('+1234567890', 'Test message')
    expect(consoleSpy).toHaveBeenCalledWith('MOCK WhatsApp to +1234567890: Test message')
    consoleSpy.mockRestore()
  })

  test('should handle real send (mocked)', async () => {
    process.env.MOCK_WHATSAPP = 'false'
    mockedAxios.post.mockResolvedValue({})

    await sendWhatsApp('+1234567890', 'Test message')
    expect(mockedAxios.post).toHaveBeenCalled()
  })

  test('should throw on real send failure', async () => {
    process.env.MOCK_WHATSAPP = 'false'
    mockedAxios.post.mockRejectedValue(new Error('API error'))

    await expect(sendWhatsApp('+1234567890', 'Test message')).rejects.toThrow('API error')
  })
})